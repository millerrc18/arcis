# Telegram + Email Audit — Sprint 4 Sub-Task Recommendations

Sprint 4 issue **#9** ("triage and remediate findings from Telegram + email sweep audit") should split into **6 sub-tasks** based on the 50 findings.

| Group | Theme | Findings folded in | Effort | Sprint 4 wave |
|-------|-------|-------------------|--------|---------------|
| **A** | NameError + silent-swallow audit | C1, CC1, I10, I12 | medium | **Wave 1 (blocker)** |
| **B** | Email subsystem hardening | C2, C4, C5, C17, I17, Nit5 | medium | Wave 2 (parallel) |
| **C** | Template hygiene + HTML-escape | C7, C15, C16, I6, I11, I15, I16 | medium | Wave 2 (parallel) |
| **D** | Mute / digest / routing policy | I1, I2, I3, I5, CC6 | large | Wave 3 (or Sprint 5) |
| **E** | Observability + dedup persistence | C11, C12, CC4 | medium | Wave 2 (parallel) |
| **F** | Coverage + operator-guide | C13, C14, I13, I14, CC3, CC5 | medium | Wave 3 (closeout) |

---

## Group A — NameError + silent-swallow audit (Wave 1, blocker)

**Goal**: Make import-time errors observable at startup, not at first runtime hit. Stop hiding NameErrors behind catch-all `except Exception`.

### Tasks

1. **Fix C1** — rename `send_telegram_message` → `send_telegram` at `overnight.py:134, 149, 304, 311`. Add regression test: `tests/notifications/test_overnight_alarm_paths.py` asserts each of the 4 alarm sites successfully invokes the real function.

2. **Build `notifications.safe_send()`** — central wrapper that:
   - Imports the target notify function explicitly (raise ImportError immediately if function not found)
   - Checks `is_telegram_enabled()` once
   - Calls notify_X
   - Catches network failures only (`urllib3.exceptions.HTTPError`, `requests.exceptions.RequestException`, `socket.timeout`, `OSError`) — NOT bare `Exception`
   - Logs at appropriate severity (warning for transient, error for repeat)
   - Increments a `notifications_sent_failed` counter (feeds into Group E)

3. **Migrate the 25+ `try/except Exception` call sites** to use `safe_send()`. This is mechanical — one-line per site.

4. **Fix I10** — replace lazy in-function imports in `cli/commands.py` with module-level imports; let `ImportError` happen at process startup.

5. **Fix I12** — break `check_action_reminders`'s function-wide `except` into per-check `except`. 5 reminders shouldn't abort together.

6. **Fold CC2** — consolidate the two `_get_telegram_config` functions into one shared helper.

**Effort**: medium. ~2-3 days for one developer in one worktree.

**Files**:
- `src/notifications/telegram.py` (add `safe_send`)
- `src/notifications/__init__.py` (re-export `safe_send`)
- `src/notifications/telegram_commands.py` (drop duplicate config loader; use shared)
- `src/scheduler/overnight.py` (rename + use safe_send)
- `src/scheduler/watch.py`, `src/scheduler/reports.py`, `src/scheduler/watch_handlers.py`, `src/shadow_trading/executor.py`, `src/services/scan_service.py`, `src/services/recap_service.py`, `src/services/watchlist_service.py`, `src/training/canary.py`, `src/training/ingestion_gate.py`, `src/training/trainer.py`, `src/risk/governor.py`, `src/evaluation/auditor.py`, `src/data_collection/research_synthesizer.py`, `src/cli/commands.py`, `src/api/cloud_routes/platform.py` (migrate to safe_send)
- `tests/notifications/test_safe_send.py` (new file)
- `tests/notifications/test_overnight_alarm_paths.py` (new file)

---

## Group B — Email subsystem hardening (Wave 2, parallel)

**Goal**: `src/email/notifier.py` has zero tests on 6 production paths. Test it; fix the 3 CRITICAL bugs in 72 LOC.

### Tasks

1. **Fix C2** — write `tests/email/test_notifier.py`. Mock `smtplib.SMTP`. Assert: dispatch envelope (To, Cc, Subject), TLS path, auth path, `from_address` fallback, ConnectionRefusedError handling.
2. **Fix C5** — `cc_addresses = email_cfg.get("cc_addresses") or []` (guard against None).
3. **Fix C4** — drop YAML password fallback. Require `EMAIL_PASSWORD` env. Add startup check: warn if `email_cfg.get("password")` is non-empty.
4. **Fix C17** — when SMTP returns False, fall over to telegram (via `safe_send` from Group A) with subject + truncated body. Persist to `notifications_sent` table (Group E).
5. **Fix I17** — replace hardcoded "2,800 examples target" with `config['training']['target_examples']`.
6. **Fix Nit5** — add smoke test placeholder.

**Effort**: medium. ~1-2 days.

**Files**:
- `src/email/notifier.py`
- `src/email/__init__.py` (re-export digest_builder per N1)
- `tests/email/test_notifier.py` (new)
- `src/email/digest_builder.py` (I17 magic number)

**Depends on**: Group A's `safe_send` for the telegram-fallback path (C17). If running in parallel, C17 can stub the call and Group A can wire the actual fallback when both land.

---

## Group C — Template hygiene + HTML-escape (Wave 2, parallel)

**Goal**: Telegram messages with bad data render as garbage or get silently rejected by the API. Add a single HTML-escape helper and a 4096-char chunked-send.

### Tasks

1. **Fix C15** — chunk message body at 4000 chars (under 4096 limit). Use `[chunk N/M]` markers. Apply to all `send_telegram` callers automatically.
2. **Fix C16** — when `notify_research_digest` truncates summary, append `[truncated; see email digest]`.
3. **Fix C7** — mirror the `notify_overnight_training_complete` `dict-with-success` pattern in `notify_overnight_complete` so non-string error values don't render as success.
4. **Fix I6** — add `_html_escape(text: str) -> str` helper. Use it on all interpolated string fields in HTML-mode notify_* (paper titles, trade tickers, error messages).
5. **Fix I11** — `notify_action_required` icons map: raise on unknown urgency instead of falling through to default.
6. **Fix I15** — normalize earnings time labels in finnhub adapter (upstream), not in `notify_position_earnings_warning`.
7. **Fix I16** — drop manual `&amp;` escapes in `notify_premarket_brief` and `notify_weekly_digest`; use `_html_escape` from #4.

**Effort**: medium. ~1-2 days.

**Files**:
- `src/notifications/telegram.py` (chunked send + html_escape + multiple notify_* updates)
- `src/data_ingestion/finnhub.py` (or wherever earnings_time normalizes) for I15
- `tests/notifications/test_telegram_chunked_send.py` (new)
- `tests/notifications/test_html_escape.py` (new)

---

## Group D — Mute / digest / routing policy (Wave 3, or Sprint 5)

**Goal**: Operator gets >100 pings/day; no quiet hours; no event→channel routing table. This is the largest group; may slip to Sprint 5.

### Tasks

1. **Fix I1** — add `notifications.policy` config: quiet_hours (start/end UTC), weekend_suppression, per-event severity → channel map.
2. **Fix I2** — add `notifications.digest` scheduler: events flagged "digest-eligible" buffer for N minutes then flush as single message.
3. **Fix I3 + CC6** — central `src/notifications/router.py` with declarative event_type → {channels, severity, prefix} table. Refactor 25+ callers to call `route_event(event_type, **kwargs)` once.
4. **Fix I5** — drop redundant `is_telegram_enabled()` wrapping at all call sites; the router checks once internally.

**Effort**: large. ~3-5 days. Multiple files touched.

**Files**:
- `src/notifications/router.py` (new, ~200 LOC)
- `src/notifications/policy.py` (new, ~80 LOC)
- `config/settings.example.yaml` (new keys)
- All caller files migrate from `notify_X(...)` to `route_event("X", ...)` (mechanical)
- `tests/notifications/test_router.py` (new)
- `tests/notifications/test_policy.py` (new)

**Decision needed**: Operator may want this in Sprint 4 if quiet hours are blocking; else Sprint 5.

---

## Group E — Observability + dedup persistence (Wave 2, parallel)

**Goal**: Cockpit dashboard cannot answer "is the bot healthy?". Add a `notifications_sent` table; persist `_DEDUP_CACHE` across watch-loop restarts.

### Tasks

1. **Fix C11** — replace `_DEDUP_CACHE = {}` (process-local) with read/write against schema-registry table `notifications_dedup` (event_type, dedup_key, sent_at). Restart-safe.
2. **Add `notifications_sent` table** (CC4) — columns: id, event_type, channel ('telegram'|'email'), recipient, sent_at, status ('ok'|'failed'|'dropped'), retry_count, error_msg.
3. **Wire `safe_send`** (Group A) and email notifier (Group B) to write to `notifications_sent` after every dispatch.
4. **Fix C12** — operator-triggered `send-test` paths add `force_send=True` kwarg to bypass silent-on-pass for `notify_validation_summary`. Add a heartbeat sentinel that writes to `notifications_sent` with `status='heartbeat'` every N hours.
5. **Add cockpit widget** — bottom-of-page "Notifications health" panel showing last 24h success/fail rate, dedup hits, oldest unack alert. Lives at `frontend/src/components/dashboard/NotificationsHealthPanel.jsx` and reads from `/api/notifications/health`.

**Effort**: medium. ~2-3 days.

**Files**:
- Schema registry: add `notifications_sent`, `notifications_dedup`
- `src/notifications/platform_events.py` (refactor `_dedup_key` to use new table)
- `src/api/cloud_routes/notifications.py` (new endpoint `/api/notifications/health`)
- `frontend/src/components/dashboard/NotificationsHealthPanel.jsx` (new)
- `frontend/src/api/api.ts` (add `getNotificationsHealth`)

**Depends on**: Group A (`safe_send` writes to the table) and Group B (email notifier writes to the table).

---

## Group F — Coverage + operator-guide (Wave 3, closeout)

**Goal**: Sprint 4 closeout — finish the test pyramid and fill the operator-guide gap.

### Tasks

1. **Fix C13** — `tests/notifications/test_telegram_commands.py` adds 17 happy-path + 17 error-path tests for the 17 command handlers. Use a single fixture for telegram bot mock.
2. **Fix C14** — `_cmd_council` typed exceptions → categorized return strings (cost_cap_exceeded, agent_timeout, llm_unavailable, no_quorum, invalid_question).
3. **Fix CC3** — convert top 4 high-traffic notify_* (`notify_trade_opened`, `notify_trade_closed`, `notify_eod_report`, `notify_weekly_digest`) to typed dataclass payloads.
4. **Fix I13** — add §X.x "Notification troubleshooting" tree to `docs/operator-guide.md` covering: bot is silent, bot token rotated, email digest stopped arriving, how to verify subsystem health.
5. **Fix I14** — document `send-test-email` CLI in `docs/telegram-commands.md`.
6. **Add CC5 send-path tests** — `test_telegram_send_path.py` and the new `test_email_notifier.py` from Group B together raise the test pyramid above SQL-filter-only.

**Effort**: medium. ~2-3 days.

**Files**:
- `tests/notifications/test_telegram_commands.py` (extend significantly)
- `tests/notifications/test_telegram_send_path.py` (new)
- `src/notifications/telegram_commands.py` (typed exceptions for council)
- `src/notifications/telegram.py` (dataclass payloads for top 4 notify_*)
- `docs/operator-guide.md` (troubleshooting section)
- `docs/telegram-commands.md` (send-test-email)

---

## Summary table — Sprint 4 dispatch order

| Wave | Groups | Why this order |
|------|--------|----------------|
| 1 | A | Blocker — must close C1 before any Sprint 4 deploy hits prod, since CUSUM/leakage/regression alerts are silently broken right now |
| 2 | B + C + E | Three medium-effort groups in parallel worktrees. No file overlap (B=email, C=telegram template, E=schema/router/dashboard) |
| 3 | F + (optional D) | Closeout. F finishes the test pyramid + operator-guide. D is large; operator-discretion whether to slip to Sprint 5 |

**Total Sprint 4 task count from #9 alone**: ~30 sub-tasks (Groups A=6, B=6, C=7, D=4, E=5, F=6).

Combined with the 10 other cockpit-coherence followups (#1-#8, #10, #11), Sprint 4 is **~40-50 tasks total** — slightly larger than Sprint 3's 23. Plan accordingly with extended timeline or scope-trim.
