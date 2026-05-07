# Telegram + Email Audit — Cross-Cutting Patterns

These are structural anti-patterns that span multiple files and produce findings at scale. Fixing them centrally is higher-leverage than fixing each downstream finding individually.

---

## CC1. The "swallow telegram failure" pattern is everywhere

Every `notify_*` call site looks like:
```python
try:
    from src.notifications.telegram import notify_X, is_telegram_enabled
    if is_telegram_enabled():
        notify_X(...)
except Exception as e:
    logger.warning("[WATCH] notify_X failed: %s", e)
```

This pattern repeats in `watch.py`, `overnight.py`, `executor.py`, `reports.py`, `watch_handlers.py`, `scan_service.py`, `canary.py`, `ingestion_gate.py`, `governor.py`, `auditor.py`, `research_synthesizer.py`, `cli/commands.py`.

**It is the structural cause of CRITICAL C1.** A bad import (NameError) is caught by the same `except Exception` that's meant to catch network failures. `send_telegram_message` doesn't exist; 4 call sites have a NameError; the wrapper makes them indistinguishable from "Telegram is down".

**Fix**: Centralize. Provide `notifications.safe_send(event, **kwargs)` that does the import + check + try/except internally; let callers be one line. Then make import-time NameErrors observable at startup, not at first runtime hit.

---

## CC2. Two notification config loaders

`src/notifications/telegram.py:_get_telegram_config` and `src/notifications/telegram_commands.py:_get_telegram_config` are identical implementations.

Sprint 4 will likely add a third config key (mute schedule, channel routing). Worth consolidating now to avoid divergence in the future.

**Fix**: One function, imported by both. Small but worthwhile.

---

## CC3. `notify_*` kwargs vs positional drift

The 30+ `notify_*` functions have 0–28 positional args. Half use type hints (`bool`, `int`, `float`); half use `int | None`. Callers must memorize signatures.

**Fix at scale**: Convert each `notify_*` to a typed payload (dataclass or TypedDict). Sprint 4 should consider this for the high-traffic functions: `notify_trade_opened`, `notify_trade_closed`, `notify_eod_report`, `notify_weekly_digest`. The other ~26 can stay positional or migrate later.

---

## CC4. No notification observability table

The schema registry has no `notifications_sent` table. The codebase has no record of "did the EOD recap actually go out today?" — only the watch loop log holds that. The cockpit dashboard cannot answer "is the bot healthy?".

**Fix**: A new `notifications_sent` table (event_type, channel, sent_at, status, retry_count) plugs into both observability and dedup (also fixes C11 dedup-cache-process-local bug).

---

## CC5. Tests cover only the SQL filtering aspects

Both `tests/notifications/test_telegram_commands.py` (125 LOC) and `tests/email/test_digest_builder.py` (231 LOC) exist primarily to assert that closed-trade queries exclude `reconciled_stale` rows. They don't test the actual rendering, the actual send path, or the actual command dispatch.

This is by intent (the audit suite was for a specific stale-row regression), but it's misleading because the test files exist and look like coverage. A new contributor reading the test count would think the modules are tested.

**Fix**: Add `test_telegram_send_path.py` (test the actual fan-out: send → API mock → assertion) and `test_email_send_path.py` (mock `smtplib.SMTP`, assert envelope). These are not regression tests; they're foundation tests.

---

## CC6. Inconsistent message prefixing

`platform_events.py:24` prepends `[RESEARCH]` to every message. Similar prefixing isn't done elsewhere — trades, scans, alerts, milestones all use emoji prefixes but no category prefix.

Operator's Telegram filter rules (mute thread, search) could benefit from consistent `[TRADE]`, `[SCAN]`, `[ALERT]`, `[OPS]`, `[RESEARCH]` prefixes across the board.

**Fix**: Add a category prefix to every notify_*. Small per-function but high-leverage for operator workflow.

---

## How these map to Sprint 4 groups

| Cross-cutting pattern | Goes into Sprint 4 group |
|-----------------------|--------------------------|
| CC1 (swallow-NameError) | **Group A — NameError + silent-swallow audit** |
| CC2 (duplicated config loaders) | Group A (consolidate when fixing CC1) |
| CC3 (positional drift) | **Group F — Coverage + operator-guide** |
| CC4 (no observability table) | **Group E — Observability + dedup persistence** |
| CC5 (SQL-only test coverage) | **Group F — Coverage + operator-guide** |
| CC6 (inconsistent prefixing) | **Group D — Mute / digest / routing policy** |

See `recommendations.md` for the full 6-group split and effort estimates.
