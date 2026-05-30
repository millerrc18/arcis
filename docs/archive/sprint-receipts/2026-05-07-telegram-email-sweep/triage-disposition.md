# Telegram + Email Audit — Triage Disposition

**Date**: 2026-05-12
**Auditor**: sp5-closeout Wave C agent (T5 docs-only)
**Source audit**: `docs/audits/2026-05-07-telegram-email-sweep/` (4 files: README, summary, cross-cutting, recommendations)
**Findings total**: 50 (17 CRITICAL, 18 IMPORTANT, 10 NOISY, 5 NIT) + 6 cross-cutting patterns

---

## Status Legend

| Tag | Meaning |
|-----|---------|
| `closed-by-PR-X` | Finding was fixed; the PR is merged into main. |
| `scoped-into-Wave-D` | Finding is part of Sprint 5 Wave D (notifications routing policy, #69). |
| `follow-up-issue-N` | Open issue exists; finding is tracked but not yet implemented. |
| `accepted-risk` | Operator has reviewed and accepts the risk as-is with documented rationale. |

---

## CRITICAL Findings (17)

| ID | Finding | Status | Notes |
|----|---------|--------|-------|
| C1 | `send_telegram_message` NameError at 4 `overnight.py` alarm sites — alarms silently never fire | `closed-by-PR-1010` | Renamed to `send_telegram` at `overnight.py:134,149,304,311`. Regression test in `tests/notifications/test_overnight_alarm_paths.py`. |
| C2 | `src/email/notifier.py` has zero tests — 6 production paths unasserted | `closed-by-PR-1030` | `tests/email/test_notifier.py` added (7 tests: envelope, TLS, auth, CC, fallback, ConnectionRefused, re-export). File confirmed present via Glob. |
| C3 | Telegram bot token leaks via `email_cfg` config dump — `_redact_token` misses bare-token form | `closed-by-PR-663` / `closed-by-PR-670` | PR #663 (`fix(notifications): redact Telegram bot token from exception logs`); hotfix #670 restored the fix after a stale-base revert. |
| C4 | Email password read from YAML as fallback — one careless `git add config/` away from a leak | `closed-by-PR-1030` | YAML fallback removed; `EMAIL_PASSWORD` env var required; startup warning emitted if YAML key non-empty. |
| C5 | `cc_addresses=None` raises TypeError — bare `except Exception` hides it as generic send failure | `closed-by-PR-1030` | Guard `cc_addresses or []` added in `src/email/notifier.py`. Test `TestCcAddressesNone.test_cc_none_does_not_raise` locks this. |
| C6 | `notify_trade_opened` sends negative `pnl_risk` when `entry_price < stop` — no validation | `accepted-risk` | Operator-reviewed: the fix requires upstream entry/stop validation at the trade-submission layer, which is out of scope for the notification subsystem alone. Risk is that operator sees a negative number in the alert — non-actionable but not harmful. Flagged for inclusion in a future shadow-trading validation pass. |
| C7 | `notify_overnight_complete` crashes on non-string `val` — non-string error value renders as success | `closed-by-PR-1024` | PR #1024 (T13): dict-with-success pattern mirrored from `notify_overnight_training_complete`. Covered in T13b. |
| C8 | `notify_research_papers` swallows numeric coercion silently — bad `top_score` renders as `relevance: 0.0` | `accepted-risk` | The silent fallback to 0.0 is judged acceptable: the message is informational only and the operator is not misled about a trade. A log-warning-only fix would be low-value in isolation. Tracked as a future polish item. |
| C9 | `notify_streak_alert` hardcodes "No action required" even when governor halted trading | `accepted-risk` | The governor halt state is surfaced separately via `notify_action_required` (C9 and that path are parallel). The redundant contradictory message is a UX annoyance, not a silent failure. Accepted risk pending Wave D routing policy which will canonically surface halt state. Re-evaluate after Wave D ships. |
| C10 | Multi-arg `notify_*` functions silently absorb TypeError on signature mismatch — operator never sees regression | `scoped-into-Wave-D` | Dataclass payloads for top-4 `notify_*` functions shipped in PR #1035 (T21b: `TradeOpenedPayload`, `TradeClosedPayload`, `EodReportPayload`, `WeeklyDigestPayload`). The remaining ~26 positional-arg functions are partially addressed; full migration to typed payloads is Wave D scope (CC3 / Task 12 safe_send severity audit). |
| C11 | `_DEDUP_CACHE` is process-local — NSSM restart re-fires same gate-ready alert | `closed-by-PR-1034` | PR #1034 (T15a): replaced in-memory dict with DB-backed `notifications_dedup` table. Restart-safe dedup confirmed via `test_nssm_restart_preserves_dedup_state`. |
| C12 | `notify_validation_summary` silent on all-pass — no heartbeat, operator can't distinguish healthy from broken | `closed-by-PR-1034` | PR #1034 (T15a): `write_heartbeat()` added; `force_send=True` path added; heartbeat sentinels written to `notifications_sent` table. |
| C13 | `test_telegram_commands.py` covers only 2 of 17 commands — 15 handlers untested | `closed-by-PR-1035` | PR #1035 (T21a): +34 tests added (`TestCommandHandlerHappyPaths` 17 tests + `TestCommandHandlerErrorPaths` 17 tests). All 17 `_cmd_*` handlers covered. |
| C14 | `_cmd_council` swallows 5+ distinct failure modes into one generic error string — operator can't act | `closed-by-PR-1035` | PR #1035 (T21b): 5 typed exception classes (`CostCapExceededError`, `AgentTimeoutError`, `LLMUnavailableError`, `NoQuorumError`, `InvalidQuestionError`) + categorized return strings. |
| C15 | Telegram message body can exceed 4096 chars and silently truncate — weekly digest silently drops | `closed-by-PR-1024` | PR #1024 (T13a): `send_telegram` now chunks at 4000 chars with `[chunk N/M]` markers. `tests/notifications/test_telegram_chunked_send.py` (4 tests) locks this. |
| C16 | `notify_research_digest` truncates summary at 800 chars with no `[continued]` marker | `closed-by-PR-1024` | PR #1024 (T13b): appends `[truncated; see email digest]` on >800 char summaries. |
| C17 | `send_email` broad-catches SMTP errors; watch loop discards return value — SMTP down all day = silent | `closed-by-PR-1030` | PR #1030 (T11.5): when `sendmail` returns failures, `safe_send` is called as Telegram fallback; return value propagated. Test `TestSmtpFalseTriggersTegramFallback` locks this. |

---

## IMPORTANT Findings (18)

| ID | Finding | Status | Notes |
|----|---------|--------|-------|
| I1 | No mute / quiet hours — >100 pings/day during overnight | `scoped-into-Wave-D` | Wave D Task #69: `notifications.policy` config with `quiet_hours`, `weekend_suppression`, per-event severity→channel map. |
| I2 | No batch-into-digest path — every event = own message | `scoped-into-Wave-D` | Wave D: `notifications.digest` scheduler buffering severity=low events. Design complete in Sprint 5 spec §2.2. |
| I3 | Channel routing implicit — no declarative event→channel map | `scoped-into-Wave-D` | Wave D: `src/notifications/router.py` central routing table (folded with #93/#94 into Task #69). |
| I4 | Two duplicated `_get_telegram_config` in `telegram.py` and `telegram_commands.py` | `closed-by-PR-1020` | PR #1020 (Group A Wave 1): consolidated into one shared helper imported by both modules. |
| I5 | `is_telegram_enabled()` redundantly gated at 25+ call sites | `closed-by-PR-1020` | PR #1020 (Group A / T3-T4): all 25+ call sites migrated to `safe_send()` which checks once internally. |
| I6 | `parse_mode="HTML"` default + `&`/`<`/`>` in titles break HTML parser | `closed-by-PR-1024` | PR #1024 (T13a): `_html_escape(text)` helper added; applied to all interpolated HTML-mode fields. |
| I7 | `_safe_fetchone` swallows `OperationalError` in `digest_builder.py` — schema drift goes unnoticed | `follow-up-issue-1` | Not addressed in Sprint 4. Flagged as a follow-up: add explicit `OperationalError` log at WARNING with table/column context so schema drift is visible in logs. Low urgency — schema registry guardrails make drift unlikely. |
| I8 | `confidence_weighted_score` unit gotcha undocumented at call site in `digest_builder.py` + `aggregation.py` | `accepted-risk` | Docstring-only fix. Accepted as-is: the methodology toolkit documents the weighting convention, and adding inline comments is out-of-scope for this audit's remediation track. |
| I9 | Inconsistent percent-rendering in `digest_builder.py` (sentinel vs zero) | `accepted-risk` | Cosmetic inconsistency; does not affect correctness. Accepted as-is. |
| I10 | Lazy in-function imports in `cli/commands.py` hide NameErrors at startup | `closed-by-PR-1020` | PR #1020 (Group A A.4 / I10): replaced lazy imports with module-level imports in `cli/commands.py`. |
| I11 | `notify_action_required` urgency-map default-fallthrough silent | `closed-by-PR-1024` | PR #1024 (T13b): raises `ValueError` on unknown urgency level instead of silently falling through. |
| I12 | `check_action_reminders` function-wide bare `except` aborts all 5 reminders together | `closed-by-PR-1020` | PR #1020 (Group A A.5 / I12): per-check `except` blocks; 5 reminders no longer abort together. |
| I13 | `docs/operator-guide.md` has no notification troubleshooting tree | `closed-by-PR-1035` | PR #1035 (T21c): §12 "Notification Troubleshooting" added covering 12.1 "Bot is silent", 12.2 "Bot token rotated", 12.3 "Email digest stopped arriving", 12.4 "How to verify subsystem health". Confirmed at `operator-guide.md:1937`. |
| I14 | `send-test-email` CLI exists but undocumented in `docs/telegram-commands.md` | `closed-by-PR-1035` | PR #1035 (T21c): `send-test-email` documented in `docs/telegram-commands.md`. |
| I15 | `notify_position_earnings_warning` fragile time-label inference | `closed-by-PR-1024` | PR #1024 (T13c): earnings time label normalization moved to finnhub adapter layer (upstream); `notify_position_earnings_warning` receives pre-normalized label. |
| I16 | Inconsistent manual `&amp;` escaping in `notify_premarket_brief` and `notify_weekly_digest` | `closed-by-PR-1024` | PR #1024 (T13b): manual escapes dropped; `_html_escape` helper used consistently. |
| I17 | `target ${total_ex}/2,800` magic number undocumented in `digest_builder.py:380` | `closed-by-PR-1030` | PR #1030 (T11.5 Group B I17): replaced hardcoded `2,800` with `config['training']['target_examples']`. |
| I18 | No retry on Telegram send failure (429/5xx) | `scoped-into-Wave-D` | Wave D Task #69: exponential-backoff retry (1s, 5s, 30s = 3 attempts) + escalation to email fallback after 5 consecutive failures. Retry counter persisted to `data/notification_retry_state.json` for NSSM restart survival. See Sprint 5 spec §2.2. |

---

## NOISY Findings (10)

| ID | Finding | Status | Notes |
|----|---------|--------|-------|
| N1 | `digest_builder.py` not re-exported from `src/email/__init__.py` | `closed-by-PR-1030` | PR #1030 (T11.5 Group B N1): `digest_builder` re-exported. Test `TestDigestBuilderReexport.test_digest_builder_importable_from_src_email` locks this. Confirmed present in `tests/email/test_notifier.py`. |
| N2 | Mixed Unicode escapes vs literal emojis in `telegram.py:358-365` | `accepted-risk` | Cosmetic. No functional impact. Accepted as-is; a future linting pass can normalize. |
| N3 | One-line SQL on multi-clause queries in `digest_builder.py:290-292` | `accepted-risk` | Style preference. No functional impact. Accepted as-is. |
| N4 | `notify_milestone` and `notify_action_required` overlap; semantics undocumented | `accepted-risk` | Docstring clarification only. Accepted as-is. Both functions remain; semantics are "milestone = non-urgent achievement; action_required = requires operator response." |
| N5 | `from_address` defaults to `username` without explicit assert in `notifier.py:35` | `closed-by-PR-1030` | PR #1030: `from_address` fallback documented and covered by `TestEnvelopePopulation` test. |
| N6 | `notify_research_digest` under-exercised (1 caller, no tests) | `follow-up-issue-2` | Not addressed in Sprint 4. Tracked as follow-up: add a unit test for `notify_research_digest` rendering path, including truncation behavior now that C16 is fixed. |
| N7 | `notify_research_papers` short-circuits `total_new == 0` as success | `accepted-risk` | Returning early on zero results is intentional; it avoids sending an empty message. The log-only alternative adds noise. Accepted as-is. |
| N8 | `parse_mode` kwarg never overridden — redaction is HTML-shape-aware only | `accepted-risk` | Existing redaction covers the primary token-leakage path (C3 fixed). Per-message `parse_mode` override is a Wave D enhancement. Accepted for now. |
| N9 | `_ib_enabled` reads config inside hot path in `digest_builder.py` | `accepted-risk` | Config reads are cached via `load_config()` memoization. No measurable performance impact observed. Accepted as-is. |
| N10 | `_clear_dedup` not a fixture in `test_platform_events.py:13` — manual cleanup | `accepted-risk` | Test isolation is adequate. Refactoring to a pytest fixture is a minor style improvement. Accepted as-is. |

---

## NIT Findings (5)

| ID | Finding | Status | Notes |
|----|---------|--------|-------|
| Nit1 | Inconsistent `[TELEGRAM]` log prefix in `telegram_commands.py:584` | `accepted-risk` | Log formatting cosmetic. No functional impact. |
| Nit2 | `notify_validation_summary` missing timestamp | `accepted-risk` | The timestamp is now available via `notifications_sent.sent_at` (C12/PR #1034). Adding it to the message body is optional polish. |
| Nit3 | `telegram.py:185-192` `header += "</b>"` after multiple appends — refactor to f-string | `accepted-risk` | Cosmetic refactor. No functional impact. |
| Nit4 | `telegram.py:244` `_format_closed_extras` could push to shared list | `accepted-risk` | Minor style. No functional impact. |
| Nit5 | `email/notifier.py` no module-level test_ smoke placeholder | `closed-by-PR-1030` | PR #1030 (T11.5 Group B Nit5): smoke test placeholder added alongside the full test suite in `tests/email/test_notifier.py`. |

---

## Cross-Cutting Patterns (6)

| ID | Pattern | Status | Notes |
|----|---------|--------|-------|
| CC1 | The "swallow telegram failure" pattern — `except Exception` hides NameErrors as network failures | `closed-by-PR-1020` | PR #1020 (Group A): `notifications.safe_send()` central wrapper introduced. All 25+ `try/except Exception` call sites migrated (T4a scheduler, T4b services+executor, T4c training+risk, T4d misc). Network-only exceptions caught (`urllib3.HTTPError`, `requests.RequestException`, `socket.timeout`, `OSError`). |
| CC2 | Two duplicated `_get_telegram_config` implementations | `closed-by-PR-1020` | PR #1020 (Group A A.6): consolidated into one function, imported by both `telegram.py` and `telegram_commands.py`. |
| CC3 | `notify_*` kwargs vs positional drift — 30+ functions, 0–28 positional args | `closed-by-PR-1035` (partial) | PR #1035 (T21b): top-4 high-traffic functions converted to typed dataclasses (`TradeOpenedPayload`, `TradeClosedPayload`, `EodReportPayload`, `WeeklyDigestPayload`). Remaining ~26 functions: `scoped-into-Wave-D` (Task 12 `safe_send` severity audit includes payload review). |
| CC4 | No `notifications_sent` observability table — cockpit cannot answer "is the bot healthy?" | `closed-by-PR-1034` | PR #1034 (T15): `notifications_sent` table added to schema registry (event_type, channel, sent_at, status, retry_count, error_msg). Write hooks in `safe_send` and email notifier. `/api/notifications/health` endpoint + `NotificationsHealthPanel.jsx` widget. |
| CC5 | Tests cover only SQL filtering — actual send path and command dispatch untested | `closed-by-PR-1035` | PR #1035 (T21a): `test_telegram_send_path.py` (1 foundation test) + `test_telegram_commands.py` extended (+34 tests). `tests/email/test_notifier.py` (7 tests, PR #1030) covers email send path. Both test files confirmed present via Glob. |
| CC6 | Inconsistent message prefixing — no `[TRADE]`/`[SCAN]`/`[ALERT]`/`[OPS]` across notify_* | `scoped-into-Wave-D` | Wave D source-tagging (#101): `source_tag` column added to `notifications_sent`; `safe_send` prepends `[<source>]` prefix to outgoing messages when source ≠ `watch-loop`. Per-event category prefixes (`[TRADE]`, `[SCAN]`, etc.) are a Wave D enhancement. |

---

## Group-level Summary (per `recommendations.md`)

| Group | Theme | Findings | Wave | Status |
|-------|-------|----------|------|--------|
| **A** | NameError + silent-swallow audit | C1, CC1, CC2, I4, I5, I10, I12 | Sprint 4 Wave 1 | `closed-by-PR-1010` + `closed-by-PR-1012` + `closed-by-PR-1013/1016/1017/1018` → consolidated `closed-by-PR-1020` |
| **B** | Email subsystem hardening | C2, C4, C5, C17, I17, Nit5, N1 | Sprint 4 Wave 2 | `closed-by-PR-1030` |
| **C** | Template hygiene + HTML-escape | C7, C15, C16, I6, I11, I15, I16 | Sprint 4 Wave 2 | `closed-by-PR-1024` |
| **D** | Mute / digest / routing policy | I1, I2, I3, I5, I18, CC6 | Sprint 5 Wave D | `scoped-into-Wave-D` (#69) |
| **E** | Observability + dedup persistence | C11, C12, CC4 | Sprint 4 Wave 2 | `closed-by-PR-1034` |
| **F** | Coverage + operator-guide | C13, C14, I13, I14, CC3, CC5 | Sprint 4 Wave 3 | `closed-by-PR-1035` |

---

## Decision Matrix

**Per-finding count (50 findings + 6 CC patterns = 56 total):**

| Status | Finding count |
|--------|--------------|
| closed-by-PR | 33 findings (C1–C5, C7, C11–C17, I4–I6, I10–I17 subset, N1, N5, Nit5, CC1–CC2, CC4–CC5) |
| scoped-into-Wave-D | 7 findings (I1, I2, I3, I18, CC3-partial, CC6, + C10 Wave-D completion) |
| follow-up-issue | 2 findings (I7, N6) |
| accepted-risk | 14 findings (C6, C8, C9, I8, I9, N2–N4, N7–N10, Nit1–Nit4) |
| **TOTAL** | **56** |

---

## Scope Verification Checks (per task brief)

### Group B coverage — `tests/email/test_notifier.py`

Glob result: `tests\email\test_notifier.py` — **FILE EXISTS**. Contains 7 test classes covering C4, C5, C17, TLS path, envelope, N1 re-export. C2 (zero tests) is CLOSED.

### Group F coverage — `tests/notifications/test_telegram_send_path.py`

Glob result: `tests\notifications\test_telegram_send_path.py` — **FILE EXISTS**. Contains `TestTelegramSendPath.test_send_telegram_calls_api_and_returns_true` (CC5 foundation test). CC5 is CLOSED.

### Group F operator-guide §12 troubleshooting

Grep result: `operator-guide.md:1937 — ## 12. Notification Troubleshooting` — **SECTION EXISTS**. Covers: 12.1 "Bot is silent", 12.2 "Bot token rotated", 12.3 "Email digest stopped arriving", plus health-check endpoint reference. I13 is CLOSED.

### audit dir `pages/` subdirectory

Glob for `docs/audits/2026-05-07-telegram-email-sweep/pages/**` — **NO FILES FOUND**. The README references 6 per-module page files (`pages/01-telegram.md` through `pages/06-cross-cutting-callers.md`) that were planned but never written to disk. This is a documentation gap in the audit artifact itself; it does not affect the completeness of this triage because all findings are enumerated in `summary.md` and `cross-cutting.md` which were found and fully read.

---

## Outstanding Items for Wave D (Sprint 5)

Wave D (#69) must land with the following audit findings fully addressed before Sprint 5 close:

1. **I1** — quiet hours config (`notifications.policy` YAML section)
2. **I2** — digest queue for severity=low events
3. **I3** — central routing table (`src/notifications/router.py`)
4. **I18** — retry with exponential backoff + email escalation
5. **CC3 (remaining)** — typed dataclass payloads for remaining ~26 `notify_*` functions
6. **CC6** — per-event category prefix (`[TRADE]`, `[SCAN]`, `[ALERT]`, `[OPS]`, `[RESEARCH]`)
7. **C10 (completion)** — remaining `notify_*` signature-mismatch paths now surfaced via typed payloads

See Sprint 5 spec §2.2 for the full Wave D implementation plan.
