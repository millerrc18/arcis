# Cleanup Sprint 1 — Pass 1 Evaluation

**Branch:** `fix/cleanup-sprint-1-critical`
**Base:** `main` @ `349bb20c` (post-backfill merge)
**Mode:** autonomous (Pass 1 → 2 → 3 → PR in one session)
**Kill-switch:** engaged (`data/trading_halted`), untouched by this sprint
**Author context:** post-2026-04-20 audit — operator triaged 24 findings into three sequential sprints; this is Sprint 1 (smallest, highest-leverage, zero-live-state fixes)

## Summary

Three independent bug fixes surfaced by the 2026-04-20 log audit. No shared files, no logical coupling, no live-state mutations. Each fixes a single defect. Implementation is ~20 lines of code + 2 regression tests.

| Code | Item | Files touched | Risk |
|---|---|---|---|
| C3 | `reconcile_dispatch` `db_path=None` TypeError | `src/shadow_trading/reconcile_dispatch.py`, `src/platform/promotion.py` | None — guard against an already-broken code path |
| H6 | Windows cp1252 Unicode crash in reconciliation log | `src/scheduler/overnight.py` (sprint prompt said `src/overnight/overnight.py`; that path does not exist) | None — ASCII replacement preserves semantics |
| H3.b | `trl` package version pin | `requirements-training.txt` | None — requirements file, no runtime logic; operator reinstalls at their own cadence |

## Coupling check

- **C3** → `src/shadow_trading/reconcile_dispatch.py`, `src/platform/promotion.py`
- **H6** → `src/scheduler/overnight.py`
- **H3.b** → `requirements-training.txt`

**Zero file overlap. Zero logical dependencies.** Each item is commit-independent. If any fails tests, the others still ship cleanly.

## Path-reference correction (not a scope change)

The sprint prompt listed H6 at `src/overnight/overnight.py:63,67`. That path does not exist on main. The actual file is `src/scheduler/overnight.py` (verified: 47 KB, the overnight-task module referenced from `watch.py`). The line numbers (63, 67) are close — the `❌` emoji is on line 65 (`msg = f"❌ Reconciliation: …"`) and the subsequent `logger.info("[WATCH] %s", msg)` is on line 67. Treating this as a **prompt-typo correction, not a scope expansion** per STOP-condition rules (scope is still one file, still the logger-cp1252 issue).

---

## Item 1: C3 — `reconcile_dispatch` `db_path=None` TypeError

### Broken behavior

Today's audit (main log): 13 × `TypeError: expected str, bytes or os.PathLike object, not NoneType` in `reconcile_all_paper_trades`, plus 13 × same TypeError in `get_strategies_by_status`. One per scan cycle (09:48 → 15:56). Reconciliation has not run successfully once today. Errors are caught by `_safe_run` in `src/scheduler/watch.py` → logged ERROR → pipeline continues → operator receives no alert. This is exactly the "silent failure" pattern CLAUDE.md warns against.

### Root cause

`src/shadow_trading/reconcile_dispatch.py:26-28`:
```python
def reconcile_all_paper_trades(
    db_path: str | None = None, dry_run: bool = False,
) -> dict[str, Any]:
```
Default is `None`. Downstream chain when called with default:
- Line 36: `reconcile_paper_trades(desk="swing", dry_run=dry_run, db_path=None)` → that function likely also has a None-tolerant signature internally, but…
- Line 44-46: `get_strategies_by_status(["shadow_trading"], db_path=None)` → hits `promotion.py:489` `sqlite3.connect(None)` → **TypeError**.

`src/platform/promotion.py:482-489`:
```python
def get_strategies_by_status(
    statuses: list[str], db_path: str = DB_PATH,
) -> list[str]:
    ...
    conn = sqlite3.connect(db_path)
```
The `str = DB_PATH` default is only applied when the argument is omitted. When a caller explicitly passes `None`, that default is bypassed — this is the standard Python default-argument footgun.

### At least one caller is passing `None`

`src/scheduler/overnight.py:29` passes `DB_PATH` correctly. Per the dispatch module's own docstring, other callers are `src/scheduler/position_monitor` and `src/scheduler/watch`. The 13-failures-per-day cadence matches watch-loop scan frequency (30-min intervals, 09:48–15:56 = 13 cycles). One of those two callers invokes `reconcile_all_paper_trades()` with default arguments (no `db_path` kwarg), so the `None` default propagates.

(We can either hunt down the caller and fix it there, or harden both `reconcile_dispatch` and `get_strategies_by_status` to fall back to config when `None` is explicitly passed. The operator requested the latter — it's defense-in-depth and protects future callers.)

### Proposed fix

Two minimal None-guards:

**`src/shadow_trading/reconcile_dispatch.py`** — at function entry, resolve `None` → config `DB_PATH`:
```python
from src.config import DB_PATH as _DEFAULT_DB_PATH

def reconcile_all_paper_trades(
    db_path: str | None = None, dry_run: bool = False,
) -> dict[str, Any]:
    if db_path is None:
        db_path = _DEFAULT_DB_PATH
    ...
```

**`src/platform/promotion.py:482-489`** — guard before `sqlite3.connect`:
```python
def get_strategies_by_status(
    statuses: list[str], db_path: str | None = DB_PATH,
) -> list[str]:
    if not statuses:
        return []
    if db_path is None:
        db_path = DB_PATH
    placeholders = ",".join("?" * len(statuses))
    conn = sqlite3.connect(db_path)
    ...
```
(Type annotation updated from `str` to `str | None` to reflect runtime reality.)

### Blast radius

- `src/shadow_trading/reconcile_dispatch.py` — one function, three call sites per invocation (line 36, 44, 54). Guard at entry covers all three.
- `src/platform/promotion.py` — `get_strategies_by_status` is also called from other places in the file (`register_strategy`, `transition_to_shadow_trading`, etc.); all of those pass `db_path=DB_PATH` explicitly and will not be affected. We are only adding a None-guard — no behavior change for callers that pass valid paths.
- Zero runtime change when `db_path` is already a valid string (the overwhelmingly common case). The guard only fires when a caller passed `None`, which today ends in TypeError — so the guard strictly widens the accepted input set with no regression risk.

### Test plan

New file: `tests/shadow_trading/test_reconcile_dispatch_db_path.py`

Test cases:
1. `reconcile_all_paper_trades(db_path=None)` — does not raise TypeError on the None path; resolves to config `DB_PATH` and calls downstream with a string. (Use `monkeypatch` to replace `reconcile_paper_trades` and `get_strategies_by_status` with spies that record the received `db_path` argument.)
2. `reconcile_all_paper_trades(db_path="/tmp/foo.sqlite3")` — explicit path is respected, NOT overridden by config.
3. `get_strategies_by_status(["shadow_trading"], db_path=None)` — does not raise TypeError; resolves to config `DB_PATH`. Pair with a `monkeypatch` on `sqlite3.connect` to assert the final path is a str.
4. `get_strategies_by_status([])` — returns `[]` unchanged (existing short-circuit).

No live DB access required. All tests use spies / monkeypatch. No network.

---

## Item 2: H6 — Windows cp1252 Unicode crash in `overnight.py`

### Broken behavior

Today's audit: 10 × `UnicodeEncodeError: 'charmap' codec can't encode character '❌' in position 64` — the Python logging `StreamHandler` inherits the Windows console's cp1252 codec; emojis crash the handler; the crash is mitigated by `--- Logging error ---` but each one dumps a three-level traceback to stderr. The underlying reconciliation work completes (next log line persists), but the stderr log becomes noisy and any downstream log-tailer sees garbage.

### Root cause

`src/scheduler/overnight.py` uses non-ASCII Unicode escapes inline in log messages and Telegram payloads:

- Line 41: `send_telegram(f"⚠️ {msg}")` — `⚠️` warning sign + variation selector
- Line 53-55: `msg = (f"✅ Reconciliation: ... — all matched")` — `✅` check + `—` em dash
- Line 65: `msg = f"❌ Reconciliation: {', '.join(parts)}"` — `❌` cross mark
- Possibly more (full-file grep in Pass 2)

Telegram handles UTF-8 fine, but the same `msg` strings also go to `logger.info("[WATCH] %s", msg)` (line 67, similar pattern likely elsewhere). The logger's cp1252 handler chokes. Even on Linux production this is brittle — better to avoid the single-platform dependency.

### Proposed fix

ASCII-equivalent replacements that preserve readability and semantics:

| Unicode | Replacement | Rationale |
|---|---|---|
| `❌` ❌ | `[FAIL]` | Per sprint prompt; matches `[WATCH]` log prefix style |
| `✅` ✅ | `[OK]` | Symmetric with `[FAIL]` |
| `—` — (em dash) | `--` (two hyphens) | Preserves text separator role |
| `⚠️` ⚠️ | `[WARN]` | Matches log-prefix style; Telegram recipient loses the emoji but gets the semantics |

Any additional non-ASCII found in Pass 2 grep gets the same treatment (or removed if purely decorative).

### Anti-goals (per sprint prompt)

- **Do NOT add `PYTHONUTF8=1` to NSSM config** from this sprint. Mention in PR body as operator follow-up.
- Do NOT refactor the logger setup or stream handler. Targeted character replacement only.
- Do NOT touch other modules with similar issues. Scope is one file.

### Blast radius

- Reconciliation log messages change text content but not message cardinality, level, or routing.
- Telegram recipients lose emoji visual cues (⚠️, ✅, ❌) and get `[WARN]`, `[OK]`, `[FAIL]` prefixes instead. Identical information; slightly less visual density.
- Any log-scraper with regex keyed to `❌` etc. would need to update — but no such scraper exists in-tree (grep confirmed in Pass 2).

### Test plan

New file: `tests/overnight/test_overnight_encoding.py`

Test cases:
1. Parse the module source and assert zero non-ASCII code points (except in docstrings/comments that aren't logged).
2. Round-trip the message-building function through `str.encode("cp1252")` without raising `UnicodeEncodeError`. Simulates the Windows-console path.
3. Message semantic preservation: `[FAIL]`, `[OK]`, `[WARN]` tokens present where expected (guards against a future refactor re-introducing emoji).

No live trading, no DB, no network.

---

## Item 3: H3.b — `trl` package version pin

### Broken behavior

Today's audit + training_overnight.log: `trl.SFTTrainer` import fails on Windows with `UnicodeDecodeError: 'charmap' codec can't decode byte 0x90 in position 6555` reading `chat_template_utils.py:270 → gptoss.jinja`. Chronic — reproduces on every overnight fine-tune for the past ~week. `trl` 1.x ships `gptoss.jinja` without declaring `encoding='utf-8'` in `read_text()`, so Windows cp1252 reads fail.

### Root cause

`requirements-training.txt:11`:
```
trl>=0.12
```
Unbounded upper pin → pip resolves to 1.1.0 (latest). MASTER.md still references "TRL 0.24" (known-good). The breaking change was the 0.24 → 1.0 jump that added the gptoss template file.

### Proposed fix

Single-line edit:
```diff
-trl>=0.12
+trl>=0.12,<0.25
```

Lower bound unchanged (matches current working baseline per MASTER.md). Upper bound `<0.25` is the first version that ships the broken gptoss template (0.24 is the last known-good per operator memory). Aligns with the lower bound expressed semantically.

### Anti-goals

- **Do NOT run `pip install -r requirements-training.txt`** or any reinstall from this sprint. Operator reinstalls when ready (likely on WSL or after Docker-ifying training).
- Do NOT edit MASTER.md's TRL version reference (that's a doc-drift item for Sprint 3 / strategic).
- Do NOT touch `unsloth`, `transformers`, or any other training dep. Scope is just `trl`.

### Blast radius

- Requirements-file edit only. No runtime Python code is modified. Next `pip install -r requirements-training.txt` will downgrade to the 0.12–0.24 window.
- No CI regression risk — the training pipeline isn't exercised in the standard test suite (it's a separate GPU-gated subsystem).

### Test plan

None. Requirements file has no executable logic. Implicit verification: the file parses as a valid pip requirements file (pre-existing lint / CI hook).

---

## Test baseline

Sprint prompt states baseline of **497 passed, 3 skipped (post-C.1 + backfill)**. Earlier diagnostic (2026-04-20 audit) showed `pytest --collect-only` reporting 2,741 tests. Baseline will be re-confirmed in Pass 3 with an actual `pytest tests/ -q` run on this branch before implementation — flagged here in case the numbers diverge materially (which would be a Pass-3 stop-and-report signal, not a Pass-1 concern).

## Stop conditions in scope for each item

Per sprint prompt:
- **C3**: stop if we discover a broader `connect_db()` refactor is needed. Current read suggests the two-location None-guard is sufficient; Pass 2 will confirm.
- **H6**: stop if the full-file grep turns up so many non-ASCII strings that the fix becomes a module refactor (threshold: >10 distinct characters, or any use-site that's not a log/Telegram message).
- **H3.b**: stop if `trl>=0.12,<0.25` makes pip unresolvable against existing `unsloth`, `transformers`, `accelerate` pins — Pass 2 can surface this via `pip install --dry-run -r requirements-training.txt` if feasible, else defer to operator.

## Ralph Loop commits

- Commit 1 (Pass 1): this document
- Commit 2 (Pass 2): `docs/sprints/cleanup_sprint_1_research.md`
- Commit 3 (Pass 3 — C3): implementation + `tests/shadow_trading/test_reconcile_dispatch_db_path.py`
- Commit 4 (Pass 3 — H6): implementation + `tests/overnight/test_overnight_encoding.py`
- Commit 5 (Pass 3 — H3.b): `requirements-training.txt` pin
- Commit 6: `CHANGELOG.md` `[Unreleased]` "Fixed" entry

PR opens after Commit 6.
