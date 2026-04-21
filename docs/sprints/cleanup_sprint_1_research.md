# Cleanup Sprint 1 — Pass 2 Research

**Branch:** `fix/cleanup-sprint-1-critical`
**Base:** `main` @ `349bb20c`
**Prereq:** `cleanup_sprint_1_evaluation.md` (Pass 1, commit 6d315d3)

This document records the re-verification + additional context-gathering done in Pass 2, before any code is changed in Pass 3. It exists to make the code changes reviewable without re-deriving context.

---

## Item 1: C3 — `reconcile_dispatch` `db_path=None` TypeError

### Line-number re-verification (on `fix/cleanup-sprint-1-critical` @ head)

- `src/shadow_trading/reconcile_dispatch.py:26-28` — `def reconcile_all_paper_trades(db_path: str | None = None, dry_run: bool = False)`. **Confirmed.**
- `src/shadow_trading/reconcile_dispatch.py:36,44,54` — three downstream call sites receiving `db_path`. **Confirmed.**
- `src/platform/promotion.py:482-489` — `def get_strategies_by_status(statuses: list[str], db_path: str = DB_PATH)` with `sqlite3.connect(db_path)` at line 489. **Confirmed.**

### Caller inventory — which caller is actually passing `None`

`grep -n 'reconcile_all_paper_trades('` across `src/`:

| Caller | Line | `db_path` passed | Status |
|---|---|---|---|
| `src/scheduler/overnight.py:29` | postclose reconciliation | `db_path=DB_PATH` (explicit) | safe |
| `src/scheduler/watch.py:694` | intra-day throttled reconciliation | **omitted** → default `None` | **bug source** |
| `src/scheduler/position_monitor.py:70` | position-monitor reconcile | `db_path=db_path` (explicit) | safe |

Today's 13 TypeErrors match the intra-day scan cadence (09:48 → 15:56 = 13 runs at 30-min interval). Watch loop's `_run_sync_body` at `watch.py:694` is the None-source. Could be fixed at the call site alone, but per sprint prompt we harden both the dispatcher and `get_strategies_by_status` (defense in depth).

`grep -n 'get_strategies_by_status('` across `src/`:

| Caller | Line | `db_path` passed |
|---|---|---|
| `src/scheduler/watch.py:751` | platform shadow-tick | `getattr(self, "_db_path", None) or DB_PATH` — always resolves to a real path |
| `src/shadow_trading/reconcile_dispatch.py:44` | from `reconcile_all_paper_trades` | passes through caller's `db_path` — can be `None` |

Conclusion: only the `reconcile_dispatch` → `get_strategies_by_status` path actually passes `None` today. A single None-guard at `reconcile_all_paper_trades` entry would suffice, but we'll also guard `get_strategies_by_status` to protect future callers.

### Canonical `connect_db()` / config-read pattern in this codebase

CLAUDE.md rule: *"All Python SQLite connections should use `src.utils.db.connect_db()` — it applies `busy_timeout=30s` and `row_factory=sqlite3.Row` consistently. Don't write new `sqlite3.connect(...)` call sites without a timeout."*

Observation: `src/platform/promotion.py` uses raw `sqlite3.connect(db_path)` in multiple places (lines 489, 510, and more). Switching this sprint to `connect_db()` would improve CLAUDE.md compliance but would also change the runtime behavior of the promotion module (row_factory change, busy_timeout change) — **out of scope for Sprint 1**. Noted as follow-up.

For the **config-read pattern** specifically (resolving a default DB path when the caller passes `None`), the common pattern in-tree is:

```python
from src.config import DB_PATH  # singleton resolved at config import time

def foo(db_path: str | None = None):
    if db_path is None:
        db_path = DB_PATH
    ...
```

Found 31 files that already `from src.config import DB_PATH` (sampled: `src/commands/executor.py`, `src/startup_checks.py`, `src/logging/activity.py`, `src/packets/eod_recap.py`, etc.). Adding this import + guard to `reconcile_dispatch.py` and tightening the existing one in `promotion.py` follows established convention.

### Confirmed Pass 1 fix is still correct

- Add `from src.config import DB_PATH` at module top of `reconcile_dispatch.py`.
- At function entry of `reconcile_all_paper_trades`, `if db_path is None: db_path = DB_PATH`.
- In `get_strategies_by_status` (`promotion.py`), add same guard before `sqlite3.connect(db_path)`; widen type annotation to `str | None` to reflect runtime reality.

**No scope expansion. Pass 1 plan stands.**

---

## Item 2: H6 — Unicode in `src/scheduler/overnight.py`

### Line-number re-verification

- `src/scheduler/overnight.py:53` — `msg = (f"✅ Reconciliation: {...} local / {...} Alpaca — all matched")`
- `src/scheduler/overnight.py:54` — same message continuation (em dash lives here)
- `src/scheduler/overnight.py:65` — `msg = f"❌ Reconciliation: {', '.join(parts)}"`
- `src/scheduler/overnight.py:67` — `logger.info("[WATCH] %s", msg)` — the crash site

Sprint-prompt lines 63 and 67 are approximately correct; the emoji is on 65, logger on 67. Prompt path `src/overnight/overnight.py` is a typo — no such directory exists. Actual file: `src/scheduler/overnight.py` (47 KB).

### Full non-ASCII inventory

Two categories:

**(A) Literal non-ASCII bytes in source (42 distinct lines, 63 total occurrences):**

| Codepoint | Char | Lines | Classification |
|---|---|---|---|
| U+2014 | em dash `—` | 42 distinct lines, 43 occurrences | see sub-table below |
| U+2500 | box drawing horizontal `─` | 5 distinct lines, 20 occurrences | ALL in banner-style comments (e.g., `# ─── Telegram ───`) |

Em dash (U+2014) sub-classification by use-site:

| Use-site | Count | Risk | Action |
|---|---|---|---|
| Direct `logger.*()` call arg | 9 | **HIGH** (cp1252 crash possible) | fix |
| Direct `print(f"...")` call | 8 | LOW (PEP 528 Windows console uses WriteConsoleW) but **also** captured by NSSM stderr redirect | fix |
| `msg = f"..."` where `msg` is subsequently logged | 5 | HIGH | fix |
| Docstring | 17 | none (not emitted to console/log) | leave |
| Code comment | 2 | none | leave |
| **Total em dashes to replace** | **22** | | |

The 9 + 8 + 5 = 22 em dashes in emittable strings are the in-scope fixes. The 17 docstring + 2 comment em dashes are left alone — they never reach a logger/print path.

**(B) Unicode escape sequences in source, rendered as non-ASCII at runtime:**

| Type | Codepoint | Char | Lines | Destination | Risk |
|---|---|---|---|---|---|
| `—` | em dash `—` | 1 occurrence, L54 | logger via L67 | HIGH |
| `✅` | check mark `✅` | 1 occurrence, L53 | logger via L67 | HIGH |
| `❌` | cross mark `❌` | 1 occurrence, L65 | logger via L67 | HIGH — today's 10 crashes |
| `⚠` | warning `⚠` | 4 occurrences, L41, L109, L283, L898 | Telegram only | low |
| `️` | variation selector | 5 occurrences, L41, L109, L283, L895, L898 | Telegram only | low (pairs with preceding emoji) |
| `\U0001F3DB` | classical building `🏛` | 1 occurrence, L895 | Telegram only | low |
| `\U0001F534` | red circle `🔴` | 1 occurrence, L124 | Telegram only | low |
| `\U0001F6A8` | rotating light `🚨` | 2 occurrences, L276, L911 | Telegram only | low |

### Scope decision: what to change, what to leave

**In-scope (logger-bound, emittable non-ASCII):**
1. All 22 em dashes in logger/print/msg-then-logged paths — replace with `--`.
2. The 3 runtime escapes that reach logger (lines 53, 54, 65) — `✅` → `[OK]`, `—` → `--`, `❌` → `[FAIL]`.

**Out of scope (preserved for Telegram UX):**
- `⚠`, `🏛`, `🔴`, `🚨`, `⚠️` (variation selectors) in `send_telegram*()` calls on lines 41, 109, 124, 276, 283, 895, 898, 911. These never reach the logger. Telegram renders emoji natively. Their `except` handlers (e.g., `except Exception as e: logger.warning("... failed: %s", e)`) log only `e`, never the emoji message.

**Out of scope (non-emittable):**
- Em dashes in docstrings (17 occurrences) and comments (2 occurrences).
- Box drawings in banner comments (20 occurrences across 5 lines).

### Scope-expansion check against Pass 1 stop conditions

Pass 1 stop condition for H6: *"stop if the full-file grep turns up so many non-ASCII strings that the fix becomes a module refactor (threshold: >10 distinct characters, or any use-site that's not a log/Telegram message)."*

- **Distinct characters in scope for the fix:** 2 literal (em dash, [box drawing not-in-scope]) + 3 escape-produced (✅, ❌, em-dash-escape). **5 distinct codepoints** touched by fix. Under the 10 threshold.
- **Use-sites:** all targeted changes are in logger/print/msg-to-log paths. No "other" use-sites being changed.
- **Total edit count:** ~22 em-dash replacements + 3 escape replacements = **25 discrete character-level edits**.

25 targeted character replacements is more than the 4 that Pass 1 anticipated, but **the fix type hasn't changed** — still one-for-one string substitution, no structural changes, no new functions, no reordering. Within the spirit of the stop condition ("becomes a module refactor"). **Proceeding without stopping.**

### Test plan (unchanged from Pass 1, clarified)

New file: `tests/overnight/test_overnight_encoding.py`

1. **Static source scan**: read `src/scheduler/overnight.py`, assert that no line containing a `logger.*`, `print(`, or `msg =` substring also contains a non-ASCII byte. (This locks in the fix and prevents regressions.) Docstrings/comments are excluded.
2. **cp1252 round-trip**: call the message-building paths (or inline string constants) and assert `str(...).encode('cp1252')` does not raise.
3. **Semantic markers present**: assert `[FAIL]`, `[OK]` tokens appear where expected in reconciliation success/fail strings.

---

## Item 3: H3.b — `trl` version pin

### Pre-edit verification

`requirements-training.txt` current contents around line 11:

```
# Requires: NVIDIA GPU with CUDA 12.x, 12GB+ VRAM
#
# Install PyTorch first (match your CUDA version):
#   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
#
# Then install these:
unsloth[cu128-torch260] @ git+https://github.com/unslothai/unsloth.git
datasets>=3.0
trl>=0.12                 # ← line 11, current value
transformers>=4.46
accelerate>=1.0
bitsandbytes>=0.44
```

Post-edit target:

```
trl>=0.12,<0.25
```

### Compatibility spot-check (no reinstall)

Per sprint anti-goals, no `pip install --dry-run` or reinstall. However, a static compatibility check against the co-pinned packages:

- `datasets>=3.0` → trl 0.12–0.24 all compatible
- `transformers>=4.46` → trl 0.12 requires transformers>=4.40, trl 0.24 requires transformers>=4.46. Our floor is already 4.46 — **compatible**
- `accelerate>=1.0` → trl 0.12 needs accelerate>=0.34; trl 0.24 needs accelerate>=1.0 — **compatible at edge**
- `bitsandbytes>=0.44` → not a trl constraint — **compatible**
- `unsloth[cu128-torch260]` → current unsloth main allows trl up to (at least) 0.24 per their docs; 0.25+ introduced the SFTConfig API churn that caused the breakage

Recommendation unchanged from Pass 1: pin `trl>=0.12,<0.25`. The operator will reinstall on their schedule.

---

## Coupling re-confirmation

- C3 commit touches: `src/shadow_trading/reconcile_dispatch.py`, `src/platform/promotion.py`, `tests/shadow_trading/test_reconcile_dispatch_db_path.py`
- H6 commit touches: `src/scheduler/overnight.py`, `tests/overnight/test_overnight_encoding.py`
- H3.b commit touches: `requirements-training.txt`

Zero file overlap; zero logical dependency. Each commit is independently revertable.

---

## Pass 3 commit plan

- Commit 3 (C3): `fix(C3): guard db_path=None in reconcile_dispatch + get_strategies_by_status`
- Commit 4 (H6): `fix(H6): replace cp1252-incompatible chars in overnight.py logger paths`
- Commit 5 (H3.b): `build(H3.b): pin trl<0.25 in requirements-training.txt`
- Commit 6 (docs): `docs: CHANGELOG entry for Sprint 1`

After commit 6: run full test suite → push → open PR.

## Follow-ups (explicitly deferred — not Sprint 1)

1. Replace raw `sqlite3.connect()` calls in `src/platform/promotion.py` (and `src/shadow_trading/reconcile.py`) with `src.utils.db.connect_db()` per CLAUDE.md. — Sprint 2 candidate.
2. Add `PYTHONUTF8=1` to the watch-loop NSSM service environment. — Operator follow-up in PR body.
3. Audit Telegram emoji paths for logger leakage if their `except` blocks ever start logging `msg` instead of `e`. — Cosmetic hardening, future.
4. Clean up em dashes in docstrings (17) and banner-comment box drawings (20) — cosmetic, low priority.
5. Fix MASTER.md reference to "TRL 0.24" to match the new pin range. — Sprint 3 (doc drift).
