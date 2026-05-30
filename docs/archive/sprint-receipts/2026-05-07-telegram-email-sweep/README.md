# Sprint 4 Prerequisite Audit — Telegram + Email Notifications

**Date**: 2026-05-07
**Auditor**: codebase-archaeologist agent (re-run; original task #46 doc lost from disk)
**Scope**: notification subsystem — Telegram + email channels
**Mode**: read-only sweep, no source files modified
**Predecessor**: 2026-05-06 cockpit-coherence-sprint structural audit (mirrored format)

## Why this audit

Sprint 4 issue #9 ("notification subsystem hardening") needs concrete scope. The
original notification audit (operator task #46) was completed but the artifact
file is missing from disk — only the task tracker checkbox survives. This audit
re-establishes the truth set.

## Audit framework

Every finding is recorded as one row with five fields:

- **Severity** — one of CRITICAL / IMPORTANT / NOISY / NIT
  - **CRITICAL**: broken behavior (NameError, mute-evading, wrong channel, secret
    leakage, silent swallow of an actionable alert)
  - **IMPORTANT**: degraded UX (template that can render `None`, missing error
    handling on a path the operator depends on, stale operator-guide content,
    auth gap)
  - **NOISY**: drift from the rest of the codebase (inconsistent format, unclear
    copy, duplicated config loader)
  - **NIT**: minor polish (typo, missing docstring detail)
- **Module + line** — `src/notifications/telegram.py:347` style
- **Evidence** — 1-2 line code excerpt or behavior description
- **Fix scope** — small (single file, <30 lines) / medium (single module, <200
  lines) / large (cross-module refactor)

## Modules in scope

| Module | LOC | Tests | Test LOC | Test ratio |
|---|---|---|---|---|
| `src/notifications/telegram.py` | 1032 | `tests/test_action_reminders.py` (verified), `tests/test_expanded_notifications.py` (verified), `tests/test_live_trading.py` (verified), `tests/test_system_validator.py` (verified) | partial coverage | partial |
| `src/notifications/telegram_commands.py` | 828 | `tests/notifications/test_telegram_commands.py` | 125 | 0.15x — only 2 of 17 commands hit |
| `src/notifications/platform_events.py` | 104 | `tests/notifications/test_platform_events.py` | 91 | 0.88x — high coverage |
| `src/email/notifier.py` | 72 | none (per docstring) | 0 | 0x — UNTESTED |
| `src/email/digest_builder.py` | 409 | `tests/email/test_digest_builder.py` | 231 | 0.56x — moderate |

## Cross-cutting callers walked

The `notify_*` / `send_telegram` / `send_email` symbols are called from 29 files
under `src/`. Top callers by call-count:

- `src/scheduler/watch.py` — main loop, ~25 call sites (digest sends + telegram fan-out)
- `src/shadow_trading/executor.py` — ~30 call sites (trade lifecycle + risk alerts + milestones)
- `src/scheduler/reports.py` — premarket brief, EOD, data asset, regime, weekly, position warnings
- `src/scheduler/overnight.py` — overnight pipeline + CUSUM + leakage + research + 1-min bars
- `src/cli/commands.py` — startup notifications + CTO report + send-test handlers
- `src/services/{scan,recap,watchlist}_service.py` — packet emails + trade-opened
- `src/training/{canary,ingestion_gate,trainer}.py` — training events
- `src/api/cloud_routes/platform.py` — platform_events for backtest/promotion/demotion
- `src/data_collection/research_synthesizer.py` — research digest
- `src/risk/governor.py` — risk alerts
- `src/evaluation/auditor.py` — daily audit emails
- `src/scheduler/watch_handlers.py` — premarket-complete + trading-stats-update
- `src/scheduler/universe_scanner.py`, `src/journal/stats.py` — secondary
- `src/sync/render_sync.py`, `src/data_enrichment/enricher.py` — secondary

## Page list

This audit produces:

- `README.md` — this file (framework + scope)
- `summary.md` — top-level rollup of findings by severity
- `cross-cutting.md` — patterns appearing in 3+ modules
- `recommendations.md` — Sprint 4 fix groups with effort estimates
- `pages/01-telegram.md` — `src/notifications/telegram.py`
- `pages/02-telegram-commands.md` — `src/notifications/telegram_commands.py`
- `pages/03-email-notifier.md` — `src/email/notifier.py`
- `pages/04-email-digest-builder.md` — `src/email/digest_builder.py`
- `pages/05-platform-events.md` — `src/notifications/platform_events.py`
- `pages/06-cross-cutting-callers.md` — the 29 modules that call `notify_*`

## Read order

1. Read `summary.md` for the count + top findings.
2. Read `cross-cutting.md` for the patterns that span 3+ modules — these are the
   ones a single Sprint 4 sub-task can fix in one pass.
3. Skim `pages/06-cross-cutting-callers.md` for the most concentrated bugs (the
   `send_telegram_message` NameError lives there).
4. Read `recommendations.md` for the proposed Sprint 4 sub-task split.
5. Per-module pages are reference material for whichever sub-task an agent picks
   up.

## Constraints honored

- This audit was read-only — no source files modified.
- No sub-agents dispatched.
- Output capped at 17 CRITICAL + 33 IMPORTANT/NOISY/NIT (within the 15-20 / 30-40
  guideline from the brief).
- Format mirrors the 2026-05-06 cockpit-coherence sprint audit structure
  described in the brief (README + summary + cross-cutting + recommendations +
  pages/), even though the cockpit audit's actual on-disk layout was different.
