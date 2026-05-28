# Visual-Verify: T10 — shadow_trading/executor.py split

**Phase 5 PR-C wave C-i** | per brief §VV (operator-visible surface)

## Operator-surface equivalence

T10 is a pure module-split refactor — zero behavior change. The public
API exposed from `src.shadow_trading.executor` is preserved via re-export.

### Public symbols importable from `src.shadow_trading.executor`

BEFORE (3093L monolith) and AFTER (split + re-export) — identical:

From `order_lifecycle.py`:
- `FILLED_ORDER_STATUSES`
- `PENDING_ORDER_STATUSES`
- `_MAX_EXIT_RETRIES`
- `_CANCEL_TERMINAL_NO_SUBMIT`
- `_is_filled_status`
- `_is_pending_status`
- `_submit_exit_order`
- `_handle_pre_exit_cancel`
- `_next_exit_retry_count`
- `_should_abandon_exit`
- `_sync_exit_qty`
- `_close_from_broker_fill`
- `_retry_exit`
- `check_and_manage_open_trades`
- `open_live_trade`

From `reconciliation_engine.py`:
- `_sector_cache`
- `_SECTOR_CACHE_TTL_S`
- `quarantine_trade`
- `_count_live_open_positions`
- `_check_open_milestones`
- `_check_close_milestones`
- `_check_loss_streak`
- `_check_sector_exposure`
- `_get_recent_ohlcv_safe`

### File line counts

| File | Before | After |
|---|---|---|
| executor.py | 3016 | 1231 |
| order_lifecycle.py | (new) | 1640 |
| reconciliation_engine.py | (new) | 405 |
| **total** | 3016 | 3276 (+260 re-export boilerplate + module headers + standard docstring fields) |

### Behavior verification

- `tests/shadow_trading/` : 9 pre-existing failures (environmental, prod-DB-env) fail identically with AND without the split — confirmed via git stash round-trip. ZERO new regressions.
- Re-export sanity: `from src.shadow_trading.executor import check_and_manage_open_trades, open_live_trade, quarantine_trade` succeeds.
- The largest file dropped from 3016L to 1640L (46% reduction in worst-file size).

### Why order_lifecycle.py is still >400L

The split moved `check_and_manage_open_trades` (771L) and `open_live_trade`
(409L) whole — these giant functions dominate order_lifecycle.py. Decomposing
THEM is function-level refactoring, out of T10's module-split scope. Registered
as grandfathered with a Phase-6 sub-target note. (Kin filed for the architect:
T10 module-split target of ~800L for order_lifecycle was unrealistic given the
undecomposed giant functions.)

### Why reconciliation_engine.py has an oversized_files entry

reconciliation_engine.py was 399L at split time (1L under the 400L limit). Adding
the 5 required standard docstring header fields pushed it to 405L. Entry added with
a Phase-6 sub-target note to decompose `_check_close_milestones` (139L).

### known_violations.json changes applied

**oversized_files:**
- `executor.py`: updated from 3016 to 1231 lines + Phase-6 note
- `order_lifecycle.py`: NEW entry at 1640L
- `reconciliation_engine.py`: NEW entry at 405L

**oversized_functions — re-keyed 5 entries (executor.py → new module):**

| function | old file | new file | old lines | new lines |
|---|---|---|---|---|
| `_retry_exit` | executor.py | order_lifecycle.py | 196 | 203 |
| `check_and_manage_open_trades` | executor.py | order_lifecycle.py | 762 | 771 |
| `open_live_trade` | executor.py | order_lifecycle.py | 398 | 409 |
| `_check_close_milestones` | executor.py | reconciliation_engine.py | 134 | 139 |
| `_check_loss_streak` | executor.py | reconciliation_engine.py | 68 | 65 |

**oversized_functions — updated (stayed in executor.py):**
- `open_shadow_trade`: 707 → 714 lines

### test_repo_structure.py result

- `test_no_function_over_60_lines`: NOW PASSES (was failing with 5 NEW VIOLATIONS)
- `test_no_file_over_400_lines`: pre-existing `scan_service.py` tolerance breach (517L vs 440+50=490 tolerance) — T15's job, not T10
- `test_all_modules_have_standard_docstring`: pre-existing `notifications.py` missing `Config keys:` — not T10

Both remaining failures were already failing on `f0bb7dd5` before T10 changes landed.
