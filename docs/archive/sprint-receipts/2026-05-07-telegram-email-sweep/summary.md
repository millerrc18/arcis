# Telegram + Email Notification Audit — Summary

**Date**: 2026-05-07
**Auditor**: design-codebase-analyst (read-only walk)
**Scope**: `src/notifications/` (1,964 LOC) + `src/email/` (481 LOC) + 25+ caller sites + tests + config + operator-guide

## Counts by severity

| Severity  | Count |
|-----------|-------|
| CRITICAL  | 17    |
| IMPORTANT | 18    |
| NOISY     | 10    |
| NIT       | 5     |
| **TOTAL** | **50** |

---

## CRITICAL findings (17) — fix in Sprint 4

### C1. `send_telegram_message` is called 4 times but does not exist
**Module + line**: `src/scheduler/overnight.py:134, 149, 304, 311`
The function is `send_telegram` — `send_telegram_message` is undefined. Each call wrapped in `try/except Exception` so the NameError is silently swallowed. **Effect**: CUSUM alarms, leakage alerts, model-regression critical/warning alerts NEVER reach the operator.
**Fix scope**: small (rename in 4 call sites + regression test).

### C2. `src/email/notifier.py` has zero tests
**Module + line**: `src/email/notifier.py:1-72` (full file)
Module docstring declares `Tests: none`. SMTP auth, TLS, CC handling, ConnectionRefusedError, `from_address` fallback all unasserted. 6 runtime paths depend on this (4 daily digests, eod recap, CTO report, per-packet email, audit RED email, watchlist email).
**Fix scope**: medium (mock `smtplib.SMTP`, assert dispatch envelope + auth + CC + error branches).

### C3. Telegram bot token can leak via the `email_cfg` config dump
**Module + line**: `src/email/notifier.py:34`, `src/notifications/telegram.py:114`, `src/notifications/telegram_commands.py:43`
`_get_telegram_config()` returns a dict containing `bot_token`. `_redact_token` regex only catches the URL-form `/bot<TOKEN>/method` — bare token in a logged dict bypasses entirely.
**Fix scope**: small (`__repr__` redaction or token-fetching closure).

### C4. Email password is read from YAML as a fallback
**Module + line**: `src/email/notifier.py:34`
`password = os.environ.get("EMAIL_PASSWORD") or email_cfg.get("password", "")`. `config/settings.example.yaml:67` ships `password: your-app-password-here` as literal example. Real password is one careless `git add config/` away.
**Fix scope**: small (drop YAML fallback; require env; startup warn if YAML key non-empty).

### C5. `cc_addresses` is mutated when it shouldn't be
**Module + line**: `src/email/notifier.py:51`
`all_recipients = [recipient] + cc_addresses` raises TypeError if `cc_addresses` is None (config sets `cc_addresses: null`). Caught by bare `except Exception` and logged as generic "Failed to send email".
**Fix**: `cc_addresses = email_cfg.get("cc_addresses") or []`.

### C6. `notify_trade_opened` swallows on FK-style edge data
**Module + line**: `src/notifications/telegram.py:166-215`
`pnl_risk = (entry_price - stop) * shares`. If `entry_price < stop`, `pnl_risk` goes negative; message sends with negative risk. No validation.
**Fix scope**: small (assert ordering or send risk_alert instead).

### C7. `notify_overnight_complete` rendering crashes on non-string `val`
**Module + line**: `src/notifications/telegram.py:325-334`
A non-string error value (dict, int returncode) is silently treated as success. Operator sees green check on failed job. Inconsistent with `notify_overnight_training_complete` (line 478) which uses `status.get("success", False)`.

### C8. `notify_research_papers` swallows numeric coercion silently
**Module + line**: `src/notifications/telegram.py:763-775`
Bad `top_score` data → silently renders `relevance: 0.0` with no log.

### C9. `notify_streak_alert` says "no action required" but doesn't check governor
**Module + line**: `src/notifications/telegram.py:665-678`
Hardcoded "No action required". If streak triggered halt-state, operator gets contradictory "no action" + halted trading.

### C10. Multi-arg notify_* functions can fail silently on missing args
**Modules**: `notify_first_scan_summary` (9 args, `telegram.py:565`), `notify_eod_report` (18), `notify_weekly_digest` (28), `notify_retrain_report` (12)
TypeError on signature mismatch caught by wrapper's `except Exception`. Operator never sees regression.
**Fix scope**: medium (typed dataclass payloads or `**kwargs` with explicit None handling).

### C11. `_dedup_key` cache in `platform_events` is process-local; restarts re-fire
**Module + line**: `src/notifications/platform_events.py:26, 33-44`
`_DEDUP_CACHE = {}` is module-level. Watch loop is restarted regularly via NSSM (per CLAUDE.md memory). Same gate-ready alert re-fires after every restart.
**Fix scope**: medium (persist to schema-registry table or activity_log).

### C12. `notify_validation_summary` silent on all-pass — no heartbeat
**Module + line**: `src/notifications/telegram.py:854-912`
Operator can't distinguish "everything fine" from "notification subsystem broken". Combined with C1+C2 = no observability.

### C13. `tests/notifications/test_telegram_commands.py` covers 2 of 17 commands
**Module + line**: `tests/notifications/test_telegram_commands.py:1-125`
Only `_cmd_status`-related counters tested. `poll_commands`, `handle_command`, `check_action_reminders` (the 3 module entry points) untested at function level.

### C14. `_cmd_council` swallows everything to a generic error string
**Module + line**: `src/notifications/telegram_commands.py:574-645`
5+ distinct failure modes (cost cap, agent timeout, LLM unavailable, no quorum, invalid question) → one generic error message. Operator can't act from Telegram.

### C15. Telegram message body can exceed 4096 chars and silently truncate
**Module + line**: `src/notifications/telegram.py:125-160` (`send_telegram`)
No length check. `notify_weekly_digest` (28 fields) easily exceeds. Telegram API responds 400; logged as "Send failed: 400" but operator never sees the weekly summary.
**Fix**: chunk or truncate with explicit "[truncated]" marker.

### C16. `notify_research_digest` truncates summary at 800 chars without telling the operator
**Module + line**: `src/notifications/telegram.py:782-787`
No "[continued in email]" suffix. Operator may decide on partial info.

### C17. `send_email` exception broad-catches; watch loop continues
**Module + line**: `src/email/notifier.py:70-72` + 6+ caller sites
`except Exception as e: ...; return False`. Watch loop callers (`watch.py:467, 475, 483, 491, 760, 1093`) discard return value. SMTP down all day → every digest silently fails.
**Fix scope**: small (telegram-fallback or persist `email_failed` event for cockpit).

---

## IMPORTANT findings (18) — Sprint 4 if scope permits, else Sprint 5

| ID | Module:line | Theme | Effort |
|----|-------------|-------|--------|
| I1 | `telegram.py:59-61` | No mute / quiet hours; >100 pings/day during overnight | medium |
| I2 | (cross-cutting) | No batch-into-digest path; every event = own message | large |
| I3 | (cross-cutting) | Channel routing implicit; no "this event → telegram/email" map | medium |
| I4 | `telegram.py:104-116` + `telegram_commands.py:32-45` | Two duplicated `_get_telegram_config` | small |
| I5 | (25+ caller files) | `is_telegram_enabled` redundantly gated everywhere | medium |
| I6 | `telegram.py:771` | `parse_mode="HTML"` default; `&`/`<`/`>` in titles break HTML parser | small |
| I7 | `digest_builder.py:39-46` | `_safe_fetchone` swallows OperationalError; schema drift goes unnoticed | small |
| I8 | `digest_builder.py` + `aggregation.py:237` | `confidence_weighted_score` unit gotcha undocumented at call site | small |
| I9 | `digest_builder.py:96, :248` | Inconsistent percent-rendering (sentinel vs zero) | small |
| I10 | `cli/commands.py` + similar | Lazy imports hide NameError at startup | medium |
| I11 | `telegram.py:843-851` | `notify_action_required` urgency map default-fallthrough silent | small |
| I12 | `telegram_commands.py:236-237` | `check_action_reminders` function-wide bare except; 5 reminders abort together | small |
| I13 | `docs/operator-guide.md` (1393 LOC) | No notification troubleshooting tree | small |
| I14 | `docs/telegram-commands.md:16` | `send-test-email` exists but undocumented | small |
| I15 | `telegram.py:827-829` | `notify_position_earnings_warning` fragile time-label inference | small |
| I16 | `telegram.py:534, 715` | Inconsistent manual `&amp;` escaping across notify_* | small |
| I17 | `digest_builder.py:380` | `target ${total_ex}/2,800` magic number undocumented | small |
| I18 | `telegram.py:138-160` | No retry on Telegram send failure (429/5xx) | small |

---

## NOISY findings (10)

| ID | Module:line | Note |
|----|-------------|------|
| N1 | `src/email/__init__.py` | `digest_builder.py` not re-exported |
| N2 | `telegram.py:358-365` | Mixed Unicode escapes vs literal emojis |
| N3 | `digest_builder.py:290-292` | One-line SQL on multi-clause queries |
| N4 | `telegram.py` | `notify_milestone` and `notify_action_required` overlap; semantics undocumented |
| N5 | `email/notifier.py:35` | `from_address` defaults to `username` without explicit assert |
| N6 | `telegram.py:778-787` | `notify_research_digest` under-exercised (1 caller, no tests) |
| N7 | `telegram.py:765-766` | `notify_research_papers` short-circuits `total_new == 0` as success |
| N8 | (50+ call sites) | `parse_mode` kwarg never overridden; redaction is HTML-shape-aware only |
| N9 | `digest_builder.py` | `_ib_enabled` reads config inside hot path |
| N10 | `tests/notifications/test_platform_events.py:13` | `_clear_dedup` not a fixture; manual cleanup |

---

## NIT findings (5)

- Nit1: `telegram_commands.py:584` inconsistent `[TELEGRAM]` log prefix
- Nit2: `notify_validation_summary` missing timestamp
- Nit3: `telegram.py:185-192` `header += "</b>"` after multiple appends — refactor to f-string
- Nit4: `telegram.py:244` `_format_closed_extras` could push to shared list
- Nit5: `email/notifier.py` no module-level test_ smoke placeholder

---

## Top-3 must-fix-first

1. **C1 + CC1** (cross-cutting): `send_telegram_message` doesn't exist + structural cause is `try/except Exception` swallowing NameError as if it were a network failure. **Sprint 4 Group A blocker.**
2. **C2 + C4 + C5**: email subsystem has zero tests, password fallback to YAML, None-bug on cc_addresses. Three CRITICAL findings in 72 LOC. **Sprint 4 Group B.**
3. **C15**: 4096-char Telegram message body silently dropped on weekly digest. **Sprint 4 Group C.**

See `cross-cutting.md` for patterns and `recommendations.md` for the 6-group fix split.
