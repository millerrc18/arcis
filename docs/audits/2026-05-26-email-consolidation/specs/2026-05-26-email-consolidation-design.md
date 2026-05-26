# Issue #115 — Email Consolidation: 4-15/day → 2 daily + 1 weekly

**Type:** Refactor / Consolidation (zero new capability)
**Complexity:** complex (~14-16 files; 18 tasks in 6 batches)
**Schema migration required:** NONE
**Status:** Spec frozen for /arcis:code implementation (post-revision pass)
**Decisions Log:** 35 explicit decisions (DD-01 through DD-35); 32 original + 3 added in revision

**Companion plan:** [../plans/2026-05-26-email-consolidation.md](../plans/2026-05-26-email-consolidation.md)
---

## 1. Overview

### 1.1 Problem

Arcis emits 4-15 distinct emails per weekday plus 2-3 weekend emails. The operator's Gmail inbox has become noisy — signal is drowning in scheduled-report fanout. The system has the right primitives (`DigestQueue` + `notifications_digest_queue` + `policy.py`) but they're wired only for Telegram. Email goes through 19 distinct call sites across 10 files, 10+ of which bypass the policy gate entirely.

### 1.2 Goal

Collapse the email firehose into a **steady-state cadence** of:

1. **Pre-Open daily digest** — weekdays 07:30 ET (configurable 07:30-08:30)
2. **Post-Close daily digest** — weekdays 17:00 ET
3. **Weekly report** — Sunday 18:00 ET

…with **THREE carve-outs that fire immediately**:

- **CRITICAL audit alerts (Hybrid)** — fire immediately as today **AND ALSO** summarize in the next pre-open digest. Operator chose this in the checkpoint phase over Strict 2+1.
- **Telegram-failure escalations** — `_do_dispatch_escalated` at `telegram.py:1535-1571` (CALL at line 1557) continues firing immediate email, since Telegram-down means email is the only remaining channel.
- **Operator-explicit CLI `--email` flags** — `test-email`, `cto-report --email`, `scan --email`, `eod-recap --email`, etc. — fire immediately. These are explicit ad-hoc requests, independent of scheduled flow.

**Terminology:** This spec uses **"Pre-Open"** (not "Pre-Market") consistently for the 07:30 ET digest. The deprecated legacy YAML key remains `digest_times.premarket` for backward compatibility, but all new code, subjects, logs, and operator docs use "Pre-Open" exclusively (DA-MAJ-12 fix).

### 1.3 Non-goals

- Adding new email types
- Adding non-email channels (Telegram, Slack, Discord, mobile push)
- Changing recommendation content — only HOW/WHEN it reaches inbox
- Building a dashboard inbox view (separate effort) — but per DD-05 (revised), overflow row IDs no longer reference a non-existent dashboard URL
- Replacing Render Postgres sync — `notifications_*` tables continue to mirror with `sync_to_postgres=True`

### 1.4 Success criteria

| Criterion | Verification |
|---|---|
| Exactly 2 scheduled email digests fire on each weekday (preopen + postclose) | Production observation over 1 week post-deploy via `digest-handover-check` CLI |
| Exactly 1 weekly digest fires Sunday 18:00 ET | Production observation over 1 week post-deploy |
| Severity=critical audit alerts fire IMMEDIATELY **AND** appear in next pre-open digest | Test: `test_critical_hybrid_path` (DD-01 + DD-34) |
| Telegram-fail-fallback escalations still fire immediately | Test: `test_escalation_immediate_path` |
| Operator-explicit CLI `--email` flags continue firing immediately | Test: `test_cli_email_passthrough` |
| Every email event_type is mapped to exactly one routing slot | **Test: `test_coverage_matrix_contract` (load-bearing, AST-based — DA-MAJ-4 fix)** |
| All 11 confirmed bypass call sites re-routed (was 10 — +1 reports.py:246 per F-MAJ-1) | Test: `test_bypass_interception_<site>` per site |
| Per-tier opt-out flags work | Test: `test_tier_disabled_skips_digest` |
| Empty-tier digest produces NO email (DA-MAJ-12 fix) | Test: `test_empty_tier_does_not_send_email` |
| DST transitions handled by stdlib (zero app code) | Test: `test_digest_fires_at_correct_et_post_dst` |
| HTML + plain MIMEMultipart bodies render correctly | Test: `test_mime_multipart_structure` |
| Existing 5388 test floor not breached after PR 1 AND after PR 2 (DA-MAJ-13 fix) | CI test count ≥ 5388 net-add; PR 1 net-adds compensation tests for PR 2's planned deletions |
| Hold-over window does NOT increase inbox volume (DA-CRIT-1 fix) | Shadow-mode default: new path writes to `tmp/digest-shadow/`, not email |
| Truncated rows preserved across tiers (DA-CRIT-2 fix) | Test: `test_truncated_rows_remain_pending_or_attached_to_email` |
| Hybrid replay source-of-truth: queue rows are canonical (DA-CRIT-3 + DD-34) | Test: `test_critical_appears_in_digest_exactly_once_via_queue_row` |

---

## 2. Architecture

### 2.1 High-level flow (new)

```
Event source                  enqueue_for_email_digest()         scheduled flush by tier
─────────────────────         ───────────────────────────        ─────────────────────────
auditor.py CRITICAL ──┬─→ immediate send_email (carve-out)
                       └─→ notifications_digest_queue.enqueue(source_tag='email:preopen:critical-overflow')
auditor.py ALERT       ──→ notifications_digest_queue.enqueue(source_tag='email:postclose')
overnight Saturday-CTO ──→ notifications_digest_queue.enqueue(source_tag='email:weekly')
overnight daily-audit  ──→ notifications_digest_queue.enqueue(source_tag='email:postclose')
morning-watchlist      ──→ notifications_digest_queue.enqueue(source_tag='email:preopen')
EOD recap              ──→ notifications_digest_queue.enqueue(source_tag='email:postclose')
scan_service           ──→ notifications_digest_queue.enqueue(source_tag='email:postclose')
recap_service          ──→ notifications_digest_queue.enqueue(source_tag='email:postclose')
watchlist_service      ──→ notifications_digest_queue.enqueue(source_tag='email:preopen')
escalation (TG-fail)   ──→ send_email IMMEDIATELY (carve-out)
CLI --email flags      ──→ send_email IMMEDIATELY (carve-out)

scheduled tick (watch.py)
─────────────────────────
07:30 ET weekday ────→ DigestQueue.flush(source_tag_match='email:preopen',  dispatcher=email_dispatcher_preopen)
17:00 ET weekday ────→ DigestQueue.flush(source_tag_match='email:postclose', dispatcher=email_dispatcher_postclose)
18:00 ET Sunday  ────→ DigestQueue.flush(source_tag_match='email:weekly',    dispatcher=email_dispatcher_weekly)
```

**Note on `source_tag_match`** (DA-MAJ-9 fix): the SQL filter is `(source_tag = ? OR source_tag LIKE ? || ':%')` — exact match OR prefix-followed-by-colon. This means `email:preopen` matches itself AND `email:preopen:critical-overflow`, but does NOT match `email:preopen2` or `email:preopenedXYZ`.

### 2.2 New module: `src/notifications/email_digest.py`

**Decision DD-15:** New module (not extension of `telegram.py`).
- Rationale: `telegram.py` is already 2000 lines named after a channel. Adding email-tier aggregation there blurs separation. A new module honors the channel-agnostic surface that `policy.py` + `DigestQueue` already encode.
- Trade-off: one more module, but mirrors the `notifier.py` (email) ↔ `telegram.py` (telegram) symmetry.

**Public API:**

```python
# src/notifications/email_digest.py

from typing import Literal
TierName = Literal["preopen", "postclose", "weekly"]

# ── Routing matrix (declarative; the load-bearing source of truth) ──────────
EVENT_TO_TIER: dict[str, TierName] = {
    # auditor
    "audit_critical":            "preopen",   # Hybrid: ALSO fires immediately
    "audit_alert":               "postclose",
    "audit_red_assessment":      "postclose",
    # scheduler/overnight
    "saturday_training_report":  "weekly",
    "saturday_cto_report":       "weekly",
    "research_synthesis":        "weekly",
    # scheduler/reports + services
    "morning_watchlist":         "preopen",
    "action_packet":             "postclose",
    "eod_recap":                 "postclose",
    # legacy digest content (drained from current 4-digest sources)
    "premarket_content":         "preopen",
    "midday_content":            "postclose",   # merged into postclose
    "eod_content":               "postclose",
    "evening_content":           "postclose",   # merged into postclose (was 20:00)
    # weekly digest content (TG today, email Sunday going forward)
    "weekly_digest_content":     "weekly",
}

CARVE_OUT_TYPES: frozenset[str] = frozenset({
    "audit_critical",          # hybrid: immediate + queued
    "escalated_telegram_fail", # immediate-only
})

# ── Public functions ───────────────────────────────────────────────────────

def enqueue_for_email_digest(
    event_type: str,
    *,
    severity: str,
    payload: dict,
    conn=None,
    now_et=None,
) -> int | None:
    """Enqueue an email-bound event to the appropriate tier.

    Returns row_id on enqueue success, None when tier is disabled per config.
    Raises KeyError when event_type is not in EVENT_TO_TIER (this enforces
    the coverage-matrix contract at runtime — every emit must declare a tier).

    via_cli propagation: ALL internal helpers in service modules that take
    via_cli=True MUST pass it through to nested calls (DD-25 + DA-MAJ-8 fix).
    """
    ...

def flush_tier(
    tier: TierName,
    *,
    db_path: str | None = None,
    now_et=None,
) -> FlushResult:
    """Drain notifications_digest_queue rows for the given tier, render the
    digest body (HTML + plain), and dispatch via send_email() — OR, when in
    shadow-mode, write to tmp/digest-shadow/<tier>-YYYY-MM-DD.html instead.

    Empty-tier suppression (DD-33): if rendered body has zero events AND
    zero critical replays AND tier-specific empty-rules allow suppression,
    NO email is sent. Dedup row STILL written (tier marks complete for day).

    Uses DigestQueue.flush(source_tag_match='email:<tier>') filter
    semantics — exact match OR prefix-followed-by-colon.

    Outcome logged to notifications_sent with channel='email' (or
    channel='email_shadow' in shadow-mode).
    """
    ...

def render_digest(
    tier: TierName,
    rows: list[dict],
    *,
    db_path: str | None = None,
    now_et=None,
    top_k: int = 10,
) -> tuple[str, str, str, list[int]]:
    """Render (subject, plain_body, html_body, overflow_row_ids) for a tier.

    overflow_row_ids: row IDs that did NOT fit in top-K (DA-CRIT-2 fix).
    Caller must NOT mark these as flush_status='sent'. They are either:
      (a) attached to the email as a plain-text overflow file, OR
      (b) left as flush_status='pending' to flush in next tier window.
    See DD-05 (revised) for full semantics.

    Includes:
      - Top-K events by severity per section
      - Overflow line: "and N more — see attached overflow file"
      - For preopen tier: pulls past-24h CRITICAL rows from
        notifications_digest_queue (DD-17 revised — queue rows are
        canonical) to summarize already-fired immediates
      - For weekly tier: also queries weekly underlying tables (data_asset,
        scan_metrics, training stats) to preserve existing weekly content
    """
    ...

def preview_tier(tier: TierName, *, db_path: str | None = None) -> str:
    """Build digest body without dispatching. Used by CLI digest-preview."""
    ...

def handover_check(*, window_days: int = 7, db_path: str | None = None) -> dict:
    """Returns PASS/FAIL tripwire status for ending dual-write hold-over
    (DA-MAJ-7 fix). Surfaced via CLI `digest-handover-check`.

    Tripwires (all must PASS for hold-over to safely end):
      - past N days: zero abandoned rows in email:* source_tag
      - past N days: preopen tier flushed >= 5 weekdays (of expected weekdays)
      - past N days: postclose tier flushed >= 5 weekdays
      - past 1 weekend: weekly tier flushed exactly once
      - past N days: shadow-mode files exist for every expected tier-day pair
        (DA-CRIT-1 + DD-31 revised)
    """
    ...
```

### 2.3 Why reuse existing primitives

| Primitive | Reuse for |
|---|---|
| `notifications_digest_queue` table | Per-tier event accumulation. `source_tag` already free-form (DD-02). |
| `DigestQueue.enqueue()` | Per-event enqueue (need to extend allowlist OR bypass for email rows — DD-26). |
| `DigestQueue.flush(dispatcher=…)` | Drain with email-dispatcher (need to add `source_tag_match` filter — Task T3 revised). |
| `DigestQueue._dispatch_one_row` retry semantics | SMTP failure recovery (DD-06). max 3 attempts → abandoned. |
| `DigestQueue._recover_orphaned_in_progress` | Crash recovery on watch-loop restart. |
| `notifications_sent` table | Outcome logging. `channel='email'` rows already supported. |
| `notifications_dedup` table | Per-tier-per-day dedup (`dedup_key='email:preopen:2026-05-26'`). |
| `policy.py` | Unchanged. Tier logic layers ABOVE policy. Critical/high still bypass per rule 1. |

---

## 3. Data Model

### 3.1 No schema migration

All consolidation work uses existing columns. Per DD-02 (operator-confirmed), `notifications_digest_queue.source_tag` is the tier discriminator via prefix scheme `'email:<tier>'`. Per CLAUDE.md schema-discipline rule, this matters: any new column would require `src/schema/registry.py` edits + `validate-schema --fix` migration + Render Postgres mirror sync.

### 3.2 source_tag conventions

| Value | Meaning |
|---|---|
| `email:preopen` | Queued for next 07:30 ET pre-open digest |
| `email:postclose` | Queued for next 17:00 ET post-close digest |
| `email:weekly` | Queued for next Sunday 18:00 ET weekly digest |
| `safe_send` | (existing) Telegram-bound, untouched |
| `email:preopen:critical-overflow` | (DD-17 revised + DD-34) Marker rows for hybrid CRITICAL — canonical for digest replay |

**source_tag length contract** (DA-MIN-16 fix): source_tag column is `TEXT` in SQLite (no length limit), but the schema registry documents max 64 chars. The convention for sub-tags is `email:<tier>:<sub-tag>` with each segment ≤ 24 chars, total ≤ 64 chars. Validated at enqueue time with `assert len(source_tag) <= 64`.

### 3.3 dedup_key conventions (notifications_dedup)

Per-tier-per-day, to defend against double-fire on restart:

| dedup_key | Used by |
|---|---|
| `email:preopen:YYYY-MM-DD` | Pre-open dispatcher writes after successful send |
| `email:postclose:YYYY-MM-DD` | Post-close dispatcher writes after successful send |
| `email:weekly:YYYY-MM-DD` | Weekly dispatcher (Sunday's date) |
| `email:preopen:YYYY-MM-DD:suppressed-empty` | (DD-33) Empty-tier suppression marker |

A successful tier flush asserts no row exists in `notifications_dedup` with the matching dedup_key for today; on success, INSERT the row. Restart in same day → duplicate INSERT fails (UNIQUE index) → log + skip.

### 3.4 Verification: 5388 test-floor baseline

Per CLAUDE.md rule. **Revised approach** (DD-23 + DA-MAJ-13 fix):

**PR 1 net-add ~85-95 new tests** = (~35-45 net-new functionality tests) + (~50 compensation tests covering what `src/email/digest_builder.py` already tests).

The compensation tests are deliberately added in PR 1 so that PR 2's deletion of `digest_builder.py` + its tests does NOT breach the 5388 floor:

| PR | Net change | Test floor delta |
|---|---|---|
| Current main | — | 5388 (baseline) |
| PR 1 ships | +85-95 (45 new + 50 compensation) | 5473-5483 |
| PR 2 ships | -50 (digest_builder tests deleted) | 5423-5433 ≥ 5388 ✓ |

Inventory step: before writing tests, /arcis:code Task 17 runs `pytest --collect-only tests/email/test_digest_builder.py | wc -l` to confirm the exact compensation count. The plan's Task 17 includes this inventory as a hard prerequisite.

---

## 4. API / UI Design

### 4.1 `send_email()` HTML extension (backward-compatible)

```python
# src/email/notifier.py — signature change

def send_email(
    subject: str,
    body: str,
    to_address: str | None = None,
    *,
    html_body: str | None = None,   # NEW (DD-03)
    attachments: list[tuple[str, bytes]] | None = None,  # NEW (DD-05 revised)
) -> bool:
    """Send a multipart/alternative email if html_body is given, else plain MIMEText.

    attachments: optional list of (filename, content_bytes) pairs. Each becomes
    a MIMEApplication part attached to the message. Used by digest overflow
    files (DA-CRIT-2 fix).

    All 15 existing call sites continue working unchanged (html_body defaults
    to None, attachments defaults to None → MIMEText behavior — fully
    backward-compatible).
    """
```

When `html_body is not None` AND `attachments is None`:
- Build `MIMEMultipart('alternative')`
- Attach `MIMEText(body, 'plain')` first
- Attach `MIMEText(html_body, 'html')` second

When `attachments is not None`:
- Build `MIMEMultipart('mixed')` outer
- If html_body: nest `MIMEMultipart('alternative')` with plain + html inside
- Else: attach `MIMEText(body, 'plain')` to the mixed container
- For each (filename, content_bytes): attach `MIMEApplication(content_bytes, Name=filename)` with `Content-Disposition: attachment; filename="<filename>"`

All other behavior (auth, CC, recipients, notifications_sent logging) preserved.

### 4.2 `DigestQueue.flush()` source_tag match filter (DA-MAJ-9 fix)

```python
# src/notifications/digest_queue.py — signature extension

def flush(
    self,
    *,
    max_rows: int = 100,
    dispatcher: Callable[[dict], None],
    source_tag_match: str | None = None,   # NEW (replaces source_tag_prefix)
) -> FlushResult:
    """If source_tag_match is given, only rows whose source_tag EITHER equals
    the value OR equals the value followed by ':' (sub-tag delimiter) are
    claimed. NULL/missing source_tag never matches.

    SQL: `WHERE flush_status='pending' AND (? IS NULL
                                            OR source_tag = ?
                                            OR source_tag LIKE ? || ':%')`
    Bound: (match, match, match) — the prefix is bound THREE times (one for
    NULL check, one for exact, one for delimited-prefix).
    """
```

**Why `_match` not `_prefix`:** the original prefix scheme would have matched `email:preopen2` and `email:preopenedXYZ` (DA-MAJ-9). The colon-delimited match prevents this; the SQL is one OR clause longer but the contract is rigorous.

**Test contract:** `test_flush_with_source_tag_match_does_not_match_partial_word` asserts a row with source_tag='email:preopened' is NOT claimed by `source_tag_match='email:preopen'`.

### 4.3 Tier dispatcher signature (injected at flush time)

```python
def _email_dispatcher_for_tier(tier: TierName) -> Callable[[dict], None]:
    """Returns a closure that dispatches one row's worth of payload.

    The closure is what DigestQueue passes per-row. Since digest tiers
    aggregate multiple rows into one email body, the dispatcher
    accumulates rows in a closure-local list. flush_tier() drives this:
    pre-pass to scan rows; build body once; dispatcher then writes
    success-status for each row.
    """
```

**Critical implementation note:** Existing `DigestQueue.flush()` calls dispatcher PER ROW. The email aggregation pattern needs aggregate-then-dispatch. Solution (DD-27):

- `flush_tier()` reads rows itself (separate SELECT) to build the digest body
- Calls `send_email(subject, plain_body, html_body=html, attachments=[(overflow_file, overflow_bytes)])` once
- On success: mark INCLUDED rows as `flush_status='sent'`. Mark OVERFLOW rows EITHER as `flush_status='deferred'` (next tier window will roll them forward) OR `flush_status='attached'` (when attachment delivers them in current email) — per DD-05 (revised).
- On failure: increment `flush_attempts` for all rows including overflow (DA-CRIT-2 fix — overflow rows are NEVER silently marked sent).

`DigestQueue.flush(source_tag_match=…)` is still extended (for forward-compat / other callers), but `flush_tier()` does NOT use it directly — it operates on the queue table at a higher abstraction (aggregate-first).

### 4.4 New CLI commands

```bash
# Preview a tier's body without sending
python -m src.main digest-preview --tier preopen
python -m src.main digest-preview --tier postclose
python -m src.main digest-preview --tier weekly

# Optional: list pending events in a tier (DD-22)
python -m src.main digest-preview --tier preopen --pending

# Optional: explicit dry-run flag
python -m src.main digest-preview --tier preopen --dry-run

# NEW (DA-MAJ-7 fix): handover-readiness tripwire check
python -m src.main digest-handover-check
python -m src.main digest-handover-check --window-days 7   # default 7

# NEW (DA-MAJ-11 fix): old-vs-new content equivalence check
python -m src.main digest-handover-check --compare-window 7d
```

These commands are operator-facing and MUST be documented in `docs/operator-guide.md`.

### 4.5 YAML config changes (DD-07, DD-10, revised for DA-CRIT-1)

```yaml
# config/settings.example.yaml + config/settings.local.yaml

email:
  # Existing keys preserved (backward-compat).
  smtp_server: smtp.gmail.com
  smtp_port: 587
  use_tls: true
  username: ""
  to_address: ""
  cc_addresses: []
  from_address: ""

  # DEPRECATED — kept for backward-compat. Config loader maps these to
  # tier_times below with a logger.warning("email.digest_times.* is
  # deprecated; use email.tier_times.{preopen,postclose,weekly}").
  digest_times:
    premarket: "07:30"   # → tier_times.preopen
    midday: "12:00"      # → folded into postclose (deprecated)
    eod: "16:15"         # → tier_times.postclose (operator default shifts to 17:00)
    evening: "20:00"     # → folded into postclose (deprecated)

  # NEW (DD-10): tier-named schedule. Three tiers only.
  # Format: "HH:MM" for weekday tiers; "DOW HH:MM" for weekly. DOW is one of
  # Sun/Mon/Tue/Wed/Thu/Fri/Sat (case-insensitive). HH:MM is 24-hour with
  # ranges 00-23 / 00-59. Invalid: 25:99, "Funday 18:00", "Sun" (no time).
  # Parser raises ValueError with a remediation message at config load.
  tier_times:
    preopen: "07:30"
    postclose: "17:00"
    weekly: "Sun 18:00"

  # NEW (DD-07): per-tier on/off. When false: rows still enqueue (for audit)
  # but flush is skipped.
  tiers:
    preopen:
      enabled: true
      send_when_empty: false   # DD-33: empty-tier suppression
    postclose:
      enabled: true
      send_when_empty: false   # DD-33
    weekly:
      enabled: true
      send_when_empty: true    # DD-33: weekly always sends (has rolling P&L section)

  # NEW (DD-05 revised): truncation + overflow policy
  digest_truncation:
    top_k_per_section: 10
    overflow_strategy: "attach_overflow_file"  # one of:
      #   "attach_overflow_file"  — write rows to <tier>-overflow-YYYY-MM-DD.txt,
      #                             attach to email, mark rows attached.
      #   "defer_to_next_tier"    — overflow rows stay flush_status='pending';
      #                             next tier window picks them up.
      # NO "dashboard" option (DA-CRIT-2: dashboard URL is out-of-scope).
    overflow_attach_format: "plain"  # plain | json

  # NEW (DD-21): respect market holidays for daily digests
  holidays:
    skip_preopen_on_market_holidays: true
    skip_postclose_on_market_holidays: true
    # Weekly digest fires regardless of holidays (Sunday is non-trading anyway)

  # NEW (DD-20 revised for DA-CRIT-1): hold-over mode
  dual_write_hold_over:
    enabled: true                    # any hold-over machinery active?
    mode: "shadow"                   # NEW: "shadow" | "time_aligned" | "off"
    # mode="shadow" (default, recommended): new path renders digests but
    #   writes to tmp/digest-shadow/<tier>-YYYY-MM-DD.{html,txt} instead of
    #   email. Inbox volume unchanged from current state. Operator inspects
    #   shadow files via `cat` or browser. Old paths fire as today.
    # mode="time_aligned": new path fires email at canonical tier times;
    #   OLD paths SUPPRESS midday + evening digests (still fire premarket
    #   + EOD). Net: ~2 extra emails/day during hold-over (vs 4-6).
    # mode="off": new path is sole sender; old paths fully retired.
    #   PR 2 (separate, post-1-week) switches mode from "shadow" → "off"
    #   in `settings.local.yaml`.
    old_path_enabled: true           # DEPRECATED alias: when true == legacy
                                     # behavior == mode="shadow". When false
                                     # == mode="off". Loader emits warning
                                     # and maps to mode= equivalent.
    shadow_output_dir: "tmp/digest-shadow"  # where shadow-mode writes files

bootcamp:
  # DD-11: email_mode collapse. Today: full_stream/daily_summary/digest/silent.
  # New: silent | digest. Old values aliased to 'digest' at load with warning.
  email_mode: digest

notifications:
  # Unchanged: routing_overrides, retry_attempts, etc.
  # NEW: per-tier retry policy override (optional; falls back to global)
  # email_tier_retry_attempts: 3   # default identical to global retry_attempts
```

**Default values selected for safety** (DA-CRIT-1 fix): `mode: "shadow"` is the safest default. Operator INBOX VOLUME DOES NOT INCREASE during hold-over. Operator inspects `tmp/digest-shadow/` files at leisure. After 1 week of clean shadow files, PR 2 flips `mode: "off"` (delivers the savings).

---

## 5. Routing matrix (the load-bearing contract)

**This table IS the spec for "every event_type has exactly one tier mapping."** It is mirrored in code as `EVENT_TO_TIER` (Section 2.2) and enforced by `test_coverage_matrix_contract` (Section 7).

| # | Event source (file:CALL-line) | Function | Today's behavior | New tier | Carve-out? |
|---|---|---|---|---|---|
| 1 | `auditor.py:784` | `check_escalation` (CRITICAL) | Immediate (24h throttled) | **preopen** | **YES — hybrid (DD-01)** |
| 2 | `auditor.py:806` | `check_escalation` (ALERT) | Immediate (24h throttled) | postclose | no |
| 3 | `overnight.py:197` | `run_daily_audit` (RED) | Immediate after 16:15 ET | postclose | no |
| 4 | `overnight.py:280` | `run_saturday_reports` (training) | Sat 09:00 ET immediate | weekly | no |
| 5 | `overnight.py:339` | `run_saturday_reports` (CTO) | Sat 09:00 ET immediate | weekly | no |
| 6 | `reports.py:164` | `run_morning_watchlist` (full_stream) | 09:30 ET or CLI | preopen | no |
| 7 | `reports.py:187` | `run_saturday_reports` (training) [DUPE, DEAD CODE — F-MAJ-1] | Currently unreachable | **DELETED** | n/a |
| 8 | `reports.py:246` | `run_saturday_reports` (CTO) [DUPE, DEAD CODE — F-MAJ-1] | Currently unreachable | **DELETED** | n/a |
| 9 | `watch.py:540` | `_check_digest_schedule` (premarket) | Mon-Fri 07:30 ET | **preopen** (replaces) | no |
| 10 | `watch.py:548` | `_check_digest_schedule` (midday) | Mon-Fri 12:00 ET | postclose | no |
| 11 | `watch.py:556` | `_check_digest_schedule` (EOD) | Mon-Fri 16:15 ET | **postclose** (replaces) | no |
| 12 | `watch.py:564` | `_check_digest_schedule` (evening) | Mon-Fri 20:00 ET | postclose | no |
| 13 | `watch.py:838` | action packet send | Per-scan or CLI | postclose | no |
| 14 | `watch.py:1397` | `_run_eod_recap` (non-digest mode) | Immediate | postclose | no |
| 15 | `services/scan_service.py:376` | `perform_scan` | Per-scan or CLI | postclose | no |
| 16 | `services/recap_service.py:85` | recap helper | Per-event | postclose | no |
| 17 | `services/watchlist_service.py:61` | watchlist helper | Per-event | preopen | no |
| 18 | `telegram.py:1557` | `_do_dispatch_escalated` | Immediate | n/a — **immediate carve-out (DD-14)** | YES |
| 19 | `cli/commands.py:36` | `send-test-email` | Immediate (operator-explicit) | n/a — **immediate carve-out (DD-13)** | YES |
| 20 | `cli/commands.py:705` | `cto-report --email` | Immediate (operator-explicit) | n/a — **immediate carve-out (DD-13)** | YES |

**F-MIN-1, F-MIN-3, F-MIN-4, F-MIN-5 line-cite fixes applied:** All file:line citations above point to the actual `send_email(…)` CALL site (not the `import` statement line). Cross-referenced with grep of `send_email\(` in src/.

**F-MAJ-1 fix:** `reports.py:187` and `reports.py:246` (the duplicate `run_saturday_reports` in reports.py) are CONFIRMED DEAD CODE — no caller imports `reports.run_saturday_reports`. The wired version is `overnight.run_saturday_reports` (wired at `watch.py:2443-2444`). Task 11 (revised) DELETES the duplicate function (lines 177-250) entirely. `reports.py:164` (morning watchlist) is the only live `send_email` site in reports.py and IS rerouted.

**Total: 17 LIVE event sources + 2 dead (deleted) + 3 carve-outs = 20 distinct call sites, all mapped, zero gaps.**

### 5.1 The Hybrid CRITICAL flow (DD-01 + DD-34 revised)

When `auditor.py:784` fires for severity=critical:

1. **STEP 1 — Enqueue queue row (canonical record)** — call `enqueue_for_email_digest('audit_critical', severity='critical', payload={'category': ..., 'description': ..., 'recommendation': ..., 'fired_immediately_at': now_iso, 'subject': critical_subject, 'body': critical_body}, source_tag='email:preopen:critical-overflow')`. The payload INCLUDES the rendered subject + body — sufficient for digest replay without re-rendering.

2. **STEP 2 — Immediate email (fire-and-forget)** — call `send_email(critical_subject, critical_body)` for operator-actionability latency. The 24h throttle gate (`_audit_email_throttled`) gates ONLY this immediate send. If throttled (suppressed), the queue row from step 1 still drives next pre-open digest entry. notifications_sent row is written with `channel='email'` `event_type='audit_critical'` `status='ok'` (or `status='throttled_suppressed'` if the gate fires).

3. **STEP 3 — Next pre-open digest** — when 07:30 ET fires, `_collect_preopen_critical_replays(db_path, now_et)` queries `notifications_digest_queue` for rows where `source_tag = 'email:preopen:critical-overflow' AND flush_status='pending'` (or `'in_progress'` for crash recovery). Body section: "**Critical audit alerts fired since last digest**" with category, description, and timestamp for each. On successful render → those rows move to `flush_status='sent'` alongside other preopen rows.

**DD-34 — Single source of truth (DA-CRIT-3 fix):** The queue row IS the canonical record for digest replay. `notifications_sent` is the audit trail of WHAT FIRED IMMEDIATELY but is NOT the source for digest replay content. This means:

- A CRITICAL with throttled immediate suppressed STILL appears in the digest (the queue row exists; only the immediate-side audit row is `status='throttled_suppressed'`).
- A CRITICAL fired immediately AND in next pre-open digest produces ONE queue row (visible exactly once in digest). The immediate side has a separate `notifications_sent` row, but that row is NOT read by the digest renderer.
- Dedup rule explicit: `WHERE source_tag = 'email:preopen:critical-overflow' AND flush_status IN ('pending', 'in_progress')`. No further deduplication needed — pending rows by definition haven't fired in a digest yet.

### 5.2 CLI passthrough flow (DD-13 + DA-MAJ-8 fix)

CLI commands with `--email` flag should NOT route through `enqueue_for_email_digest()`. They continue calling `send_email()` directly. This is preserved as the operator's escape hatch.

Affected commands:
- `python -m src.main send-test-email` → unchanged
- `python -m src.main cto-report --email` → unchanged
- `python -m src.main scan --email TICKER` → unchanged
- `python -m src.main eod-recap --email` → unchanged
- `python -m src.main morning-watchlist --email` → unchanged

The non-CLI callers (auto-scheduled emails) DO route through `enqueue_for_email_digest()`. The decision branch lives in the service layer (`scan_service`, `recap_service`, `watchlist_service`) where the same function services both CLI and scheduled callers — it must detect "is this an explicit CLI call" via a new `via_cli: bool = False` kwarg.

**via_cli propagation rule** (DA-MAJ-8 fix): `via_cli=True` MUST propagate to ALL internal helper functions within the same service module. A top-level CLI call to `perform_scan(via_cli=True)` that internally calls `_emit_packet(...)` MUST pass `via_cli=True` down to `_emit_packet`. Test fixture `test_via_cli_propagates_to_helpers` enforces this:

```python
def test_via_cli_propagates_to_helpers():
    """via_cli=True at the top-level must propagate to all internal helpers."""
    from src.services import scan_service
    with patch.object(scan_service, '_emit_packet') as mock_helper:
        scan_service.perform_scan('AAPL', via_cli=True)
        for call in mock_helper.call_args_list:
            assert call.kwargs.get('via_cli') is True
```

**CLI race rule** (DA-MAJ-8 fix): a CLI command that takes >2 minutes (e.g., a multi-ticker `cto-report`) MUST NOT also call `enqueue_for_email_digest()` for the same content. CLI is operator-explicit ad-hoc; never enqueue from a CLI path. Test `test_cli_cto_report_does_not_enqueue_to_postclose` enforces this.

```python
# Pattern for service-layer callers:
def perform_scan(ticker: str, *, via_cli: bool = False, email: str | None = None) -> ScanResult:
    result = _do_scan(...)
    _emit_packet(result, via_cli=via_cli)  # propagation
    if email or via_cli:
        # Operator-explicit; bypass digest aggregation
        send_email(subject, body)
    else:
        # Scheduled flow; route through aggregator
        try:
            enqueue_for_email_digest("action_packet", severity="normal", payload={...})
        except (ImportError, ModuleNotFoundError) as e:
            # DD-30 fallback (revised — see Section 6.5)
            logger.critical('[EMAIL] aggregator import failed - FIREHOSE FALLBACK MODE: %s', e)
            try:
                from src.notifications.telegram import safe_send
                safe_send('system_event', body='CRITICAL: email_digest aggregator failed; firehose mode active', severity='alert')
            except Exception:
                pass
            send_email(subject, body)
    return result
```

### 5.3 Bypass call-site enumeration (DA-NIT-21 fix)

To resolve the 8+/10/19 count discrepancy from the original spec, here is the explicit enumeration:

| # | File | CALL line | Function (containing) | Action in this PR |
|---|---|---|---|---|
| 1 | `src/evaluation/auditor.py` | 784 | `check_escalation` (CRITICAL) | Hybrid: queue + immediate (Task 9) |
| 2 | `src/evaluation/auditor.py` | 806 | `check_escalation` (ALERT) | Replace with enqueue (Task 9) |
| 3 | `src/scheduler/overnight.py` | 197 | `run_daily_audit` | Replace with enqueue (Task 10) |
| 4 | `src/scheduler/overnight.py` | 280 | `run_saturday_reports` | Replace with enqueue (Task 10) |
| 5 | `src/scheduler/overnight.py` | 339 | `run_saturday_reports` | Replace with enqueue (Task 10) |
| 6 | `src/scheduler/reports.py` | 164 | `run_morning_watchlist` | Replace with enqueue (via_cli gate) (Task 11) |
| 7 | `src/scheduler/reports.py` | 187 | `run_saturday_reports` (DEAD) | **DELETE FUNCTION** (Task 11) |
| 8 | `src/scheduler/reports.py` | 246 | `run_saturday_reports` (DEAD) | **DELETE FUNCTION** (Task 11) |
| 9 | `src/scheduler/watch.py` | 540 | `_check_digest_schedule` (premarket) | Retire branch (Task 8) |
| 10 | `src/scheduler/watch.py` | 548 | `_check_digest_schedule` (midday) | Retire branch (Task 8) |
| 11 | `src/scheduler/watch.py` | 556 | `_check_digest_schedule` (EOD) | Retire branch (Task 8) |
| 12 | `src/scheduler/watch.py` | 564 | `_check_digest_schedule` (evening) | Retire branch (Task 8) |
| 13 | `src/scheduler/watch.py` | 838 | action packet emit | Replace with enqueue (Task 11) |
| 14 | `src/scheduler/watch.py` | 1397 | `_run_eod_recap` | Replace with enqueue (Task 11) |
| 15 | `src/services/scan_service.py` | 376 | `perform_scan` | via_cli gate (Task 12) |
| 16 | `src/services/recap_service.py` | 85 | recap helper | via_cli gate (Task 12) |
| 17 | `src/services/watchlist_service.py` | 61 | watchlist helper | via_cli gate (Task 12) |
| 18 | `src/notifications/telegram.py` | 1557 | `_do_dispatch_escalated` | Comment + audit-tag (Task 13) — **CARVE-OUT** |
| 19 | `src/cli/commands.py` | 36 | `send-test-email` | Unchanged — **CARVE-OUT** |
| 20 | `src/cli/commands.py` | 705 | `cto-report --email` | Unchanged — **CARVE-OUT** |

**Total: 20 distinct (file, line, function) tuples.** 14 are rerouted to enqueue, 2 are deleted (dead code), 3 are carve-outs (preserved), 1 (`auditor.py:784`) is hybrid (both).

---

## 6. Error handling

### 6.1 SMTP failure (DD-06)

- `send_email()` returns False on any SMTP error (existing behavior, unchanged)
- `flush_tier()` catches False return → increments `flush_attempts` for ALL row IDs included in the failed batch via direct UPDATE
- Overflow rows (the truncated ones — DA-CRIT-2) are NEVER marked `sent` on SMTP failure. They stay `pending` so the next tier flush can roll them forward.
- After 3 failed attempts (per `config.notifications.retry_attempts`), rows transition to `flush_status='abandoned'` with `flush_error` populated (truncated, redacted)
- `notifications_sent` row written with `status='failed'`, `error_msg` truncated to 200 chars
- Operator can inspect: `SELECT * FROM notifications_digest_queue WHERE flush_status='abandoned' AND source_tag LIKE 'email:%' ORDER BY id DESC`

### 6.2 Crash recovery (existing)

`DigestQueue._recover_orphaned_in_progress` runs at start of each flush. Reuses existing logic — any `'in_progress'` row where the previous flush crashed mid-dispatch is treated as a one-attempt failure. Email path inherits this for free since rows live in same table.

For the **batch-flush case** (Section 4.3): if `flush_tier()` crashes mid-batch (e.g., between `send_email()` succeeding and the bulk UPDATE), we risk re-sending the digest. Mitigation:

1. Begin transaction
2. UPDATE included row IDs to `flush_status='in_progress'`, COMMIT (atomic claim). Overflow rows remain `pending`.
3. Call `send_email(...)` with body + attachments
4. If success: UPDATE included rows to `flush_status='sent'` (or `'attached'` for the attachment-mode rows), INSERT `notifications_dedup` row with `dedup_key='email:<tier>:YYYY-MM-DD'` (which fails by UNIQUE index if a previous attempt already succeeded — providing idempotency)
5. If failure: UPDATE all included rows back to `pending` with `flush_attempts+1` (or `abandoned` if at cap). Overflow rows are untouched (already `pending`).

**Defensive isolation rule** (DA-MIN-17 fix): the transaction in step 2 uses `isolation_level='IMMEDIATE'` to acquire a reserved lock. A 07:25 ET CRITICAL race with the 07:30 ET flush can NOT corrupt the digest: either the enqueue commits before the flush's SELECT (CRITICAL appears in the digest), or after (CRITICAL stays pending for next flush). Test `test_concurrent_enqueue_during_flush_does_not_corrupt`.

**Tolerate missing payload fields** (DA-MIN-17 fix): the digest renderer's `_collect_preopen_critical_replays` MUST use `payload.get('category', 'unknown')` and `payload.get('description', '')` etc. (defensive defaults) since a partial enqueue (committed payload with missing field) must not crash the digest.

Order matters: if crash happens between (3) and (4), the next flush attempt sees `in_progress` rows, recovers them via `_recover_orphaned_in_progress` (marks as failed, increments attempts), and either retries OR abandons. The `notifications_dedup` row check on step (4) prevents double-sending after a successful-but-uncommitted send.

### 6.3 Holiday + DST handling (DD-21)

`flush_tier('preopen')` and `flush_tier('postclose')` consult `src.scheduler.holidays.is_market_holiday(check_date=now_et.date())` before sending. If True AND `config.email.holidays.skip_preopen_on_market_holidays` is True → log "[DIGEST] Skipping preopen on holiday <name>" and return early WITHOUT marking rows as sent. Rows will be sent on next trading day's tier flush.

Weekly tier ignores holidays — Sunday is always non-trading anyway. (DD-21)

DST is stdlib-handled per the codebase convention (`zoneinfo.ZoneInfo('America/New_York')`). Test added (`test_digest_fires_at_correct_et_post_dst`) parameterized over March + November DST Sunday boundaries.

### 6.4 Per-tier opt-out (DD-07)

When `config.email.tiers.<tier>.enabled = false`:
- Events STILL enqueue into `notifications_digest_queue` (audit-trail preserved)
- Scheduled tick at tier's `tier_time` SKIPS the flush
- Rows accumulate indefinitely; operator can re-enable to drain them OR run `digest-preview --tier <tier>` to inspect what would have been sent

This way "operator on vacation" enabled-vacation-mode preserves zero signal loss — events are queued, not dropped.

### 6.5 Empty-tier digest suppression (DD-33 — DA-MAJ-12 fix)

When `flush_tier(tier)` renders a body with **zero events AND zero critical replays** AND `config.email.tiers.<tier>.send_when_empty = false` (default for preopen/postclose):

- Log `[DIGEST] tier=<tier> suppressed: empty (no events queued, no critical replays)`
- DO NOT call `send_email()`
- DO INSERT `notifications_dedup` with `dedup_key='email:<tier>:YYYY-MM-DD:suppressed-empty'` (tier marks complete for the day — prevents re-attempt loop)
- Write `notifications_sent` row with `channel='email'`, `event_type='digest_<tier>'`, `status='suppressed_empty'` for audit trail

For weekly tier (`send_when_empty: true` by default — the weekly always has rolling-7-days P&L content), suppression rule does NOT apply. Weekly always sends.

Test: `test_empty_preopen_tier_does_not_send_email` — seed empty queue + no notifications_sent CRITICAL rows in past 24h; assert `send_email` NOT called; assert dedup row exists with `suppressed-empty` suffix.

### 6.6 Aggregator-import failure (DD-30 revised — DA-MAJ-10 + DA-MIN-19 fix)

If `from src.notifications.email_digest import enqueue_for_email_digest` raises ImportError at a call site (e.g., during a partial deploy), the caller MUST:

1. Log at **CRITICAL level** with explicit "FIREHOSE FALLBACK MODE" marker
2. Fire an out-of-band Telegram alert ("CRITICAL: email_digest aggregator failed; firehose mode active") — best-effort
3. Fall back to `send_email()` directly

**Crucial: catch ImportError, ModuleNotFoundError ONLY — NOT AssertionError.** This is so that the module-load `assert` in `email_digest.py` (Task 5) — which raises AssertionError if `EVENT_TO_TIER` drifts from `EMAIL_TIER_EVENT_TYPES` — is NOT silently swallowed. AssertionError in module-load = real coverage gap that needs a human fix, not a silent firehose regression.

**Per DA-MIN-19**: convert the bare `assert` in the email_digest module-load path into an explicit `raise ImportError(...)` — that way module-load failure IS caught by the try/except in callers (intended ImportError catch), BUT a true assertion violation in render code still surfaces as AssertionError and crashes hard. The module-load drift check uses ImportError for "this module cannot safely operate" semantics.

```python
# Pattern for every bypass-remediation caller:
try:
    from src.notifications.email_digest import enqueue_for_email_digest
    enqueue_for_email_digest("audit_alert", severity=sev, payload=p, source_tag="email:postclose")
except (ImportError, ModuleNotFoundError) as e:
    logger.critical('[EMAIL] email_digest import failed - FIREHOSE FALLBACK MODE: %s', e)
    try:
        from src.notifications.telegram import safe_send
        safe_send('system_event',
                  body=f'CRITICAL: email_digest aggregator import failed; firehose mode active. Error: {e}',
                  severity='alert')
    except Exception:
        pass  # best-effort; do not propagate
    from src.email.notifier import send_email
    send_email(subject, body)
# NOTE: AssertionError is NOT caught; it propagates and crashes the watch loop —
#       which is correct: assertion failure means coverage gap that needs human fix.
```

Test: `test_aggregator_assertion_failure_is_not_swallowed_as_importerror` — patch `email_digest.enqueue_for_email_digest` to raise `AssertionError`; assert the AssertionError propagates and is NOT silenced by the try/except.

Test: `test_aggregator_import_error_falls_back_with_critical_log` — patch import to raise `ImportError`; assert `logger.critical` called, `send_email` called, `safe_send` called (best-effort).

---

## 7. Testing strategy

### 7.1 The load-bearing test: `test_coverage_matrix_contract` (DA-MAJ-4 fix)

Per DD-08 + DD-16, this is the test that prevents signal loss. **Declarative dict form** (DD-16) PLUS **AST-based bypass-grep replacement** (DA-MAJ-4):

```python
# tests/notifications/test_email_digest_coverage_matrix.py

import ast
import pathlib

EXPECTED_EVENT_TO_TIER = {
    "audit_critical": "preopen",         # hybrid
    "audit_alert": "postclose",
    "audit_red_assessment": "postclose",
    "saturday_training_report": "weekly",
    "saturday_cto_report": "weekly",
    "research_synthesis": "weekly",
    "morning_watchlist": "preopen",
    "action_packet": "postclose",
    "eod_recap": "postclose",
    "premarket_content": "preopen",
    "midday_content": "postclose",
    "eod_content": "postclose",
    "evening_content": "postclose",
    "weekly_digest_content": "weekly",
}

# (file_path, function_name) tuples (DA-MAJ-4 fix: line-level, not file-level).
# Each entry justifies WHY this specific function may call send_email directly.
BYPASS_ALLOWLIST = {
    ('src/cli/commands.py', 'cmd_test_email'): 'CLI carve-out (DD-13)',
    ('src/cli/commands.py', 'cmd_cto_report'): 'CLI carve-out (DD-13)',
    ('src/notifications/telegram.py', '_do_dispatch_escalated'): 'TG-fail escalation carve-out (DD-14)',
    ('src/email/notifier.py', 'send_email'): 'the implementation function itself',
    ('src/email/__init__.py', None): 're-export shim',
    ('src/notifications/email_digest.py', '_dispatch_tier'): 'aggregator itself',
    # NOTE: reports.py removed — duplicate run_saturday_reports DELETED (F-MAJ-1)
}


def test_coverage_matrix_complete():
    """Every event_type the system can emit to email has exactly one tier."""
    from src.notifications.email_digest import EVENT_TO_TIER
    assert set(EVENT_TO_TIER.keys()) == set(EXPECTED_EVENT_TO_TIER.keys()), (
        "EVENT_TO_TIER drift detected. Add new event_types to BOTH the "
        "production map AND this test's EXPECTED_EVENT_TO_TIER dict."
    )
    for evt, tier in EXPECTED_EVENT_TO_TIER.items():
        assert EVENT_TO_TIER[evt] == tier, f"Tier mismatch for {evt}"


def test_no_orphan_send_email_call_sites():
    """AST walk: every send_email(...) call in src/ is in BYPASS_ALLOWLIST."""
    repo = pathlib.Path(__file__).resolve().parents[2]
    src_dir = repo / 'src'
    offenders = []
    for py in src_dir.rglob('*.py'):
        rel = str(py.relative_to(repo)).replace('\\', '/')
        try:
            tree = ast.parse(py.read_text(encoding='utf-8'))
        except SyntaxError:
            continue
        # Walk to find each `send_email(...)` call and its containing function.
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_name = node.name
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Call):
                        callee = _resolve_callee(inner.func)
                        if callee == 'send_email':
                            key = (rel, fn_name)
                            if key not in BYPASS_ALLOWLIST:
                                offenders.append(f"{rel}:{inner.lineno} in {fn_name}")
    assert not offenders, (
        f"Bypass call sites remain (not in allowlist): {offenders}. "
        f"Either re-route through enqueue_for_email_digest OR add to "
        f"BYPASS_ALLOWLIST with justification."
    )


def test_event_types_emitted_match_registered():
    """AST: every literal `enqueue_for_email_digest(event_type='X', ...)`
    call in src/ has X in EVENT_TO_TIER."""
    from src.notifications.email_digest import EVENT_TO_TIER
    repo = pathlib.Path(__file__).resolve().parents[2]
    src_dir = repo / 'src'
    emitted_types = set()
    for py in src_dir.rglob('*.py'):
        try:
            tree = ast.parse(py.read_text(encoding='utf-8'))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _resolve_callee(node.func) == 'enqueue_for_email_digest':
                # Expect first positional OR keyword arg event_type
                for kw in node.keywords:
                    if kw.arg == 'event_type' and isinstance(kw.value, ast.Constant):
                        emitted_types.add(kw.value.value)
                if node.args and isinstance(node.args[0], ast.Constant):
                    emitted_types.add(node.args[0].value)
    unregistered = emitted_types - set(EVENT_TO_TIER.keys())
    assert not unregistered, (
        f"event_types emitted but not registered in EVENT_TO_TIER: {unregistered}"
    )


def _resolve_callee(node) -> str | None:
    """Return the bare name of a Call node's func (handles Attribute + Name)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None
```

**Why AST not grep:** Windows is the runtime (per CLAUDE.md); grep doesn't exist there. `ast` is stdlib and platform-neutral. As a bonus, AST gives us per-function granularity, so the ALLOWLIST is `(file, function_name)` — much tighter than file-level.

This third test is the regression guard against future routing-event-type drift. New caller files/functions added to allowlist require an explicit code-review justification.

### 7.2 Per-tier rendering tests

```python
# tests/notifications/test_email_digest_render.py

def test_preopen_digest_includes_overnight_critical_replay_via_queue_row():
    """When CRITICAL fired immediately at 03:00 ET, preopen digest at 07:30 ET
    summarizes it via the notifications_digest_queue lookback (DD-34)."""
    ...

def test_postclose_digest_aggregates_action_packets():
    """5 scan_service action packets queued → postclose body shows them as a single section."""
    ...

def test_weekly_digest_includes_saturday_content():
    """Saturday CTO + training report data → Sunday weekly body has both sections."""
    ...

def test_truncation_top_k_with_overflow_attached_file():
    """100 events in a tier → body shows top 10 by severity + 'and 90 more — see attached overflow file'.
    Attached file present in MIMEMultipart('mixed'). Overflow rows marked flush_status='attached'."""
    ...

def test_truncation_top_k_with_overflow_deferred_to_next_tier():
    """With overflow_strategy='defer_to_next_tier': 100 events → top 10 in email,
    overflow 90 stay flush_status='pending' (DA-CRIT-2). Next tier flush picks them up."""
    ...
```

### 7.3 Bypass interception tests (one per call site)

```python
# tests/notifications/test_bypass_interception.py

@patch('src.notifications.email_digest.enqueue_for_email_digest')
@patch('src.email.notifier.send_email')
def test_auditor_critical_routes_both_immediate_and_queue(mock_send, mock_enqueue):
    """CRITICAL → BOTH send_email called AND enqueue called with source_tag='email:preopen:critical-overflow'."""
    from src.evaluation.auditor import check_escalation
    check_escalation({'severity': 'critical', 'category': 'risk', ...})
    assert mock_send.called
    assert mock_enqueue.called
    _, kwargs = mock_enqueue.call_args
    assert kwargs.get('source_tag') == 'email:preopen:critical-overflow'

# Etc. One test per LIVE bypass site (14 tests; 2 deleted dead-code sites have no test; 3 carve-outs have their own carve-out tests).
```

### 7.4 CLI passthrough + via_cli propagation tests

```python
def test_cli_send_test_email_calls_send_directly():
    """python -m src.main send-test-email bypasses aggregator."""
    ...

def test_cli_scan_email_flag_bypasses_aggregator():
    """python -m src.main scan --email TICKER bypasses aggregator."""
    ...

def test_scan_service_without_via_cli_routes_to_queue():
    """services.scan_service.perform_scan() without via_cli=True enqueues."""
    ...

def test_scan_service_with_via_cli_calls_send_directly():
    """services.scan_service.perform_scan(via_cli=True) bypasses."""
    ...

def test_via_cli_propagates_to_helpers():
    """DA-MAJ-8: via_cli=True propagates to ALL internal helper functions."""
    ...

def test_cli_cto_report_does_not_enqueue_to_postclose():
    """DA-MAJ-8: CLI commands MUST NOT also enqueue (would double-deliver)."""
    ...
```

### 7.5 HTML structure test

```python
def test_html_multipart_alternative_structure():
    """Both text and HTML parts present and orderable."""
    import email.parser
    subject, plain, html, _ = render_digest('preopen', _seed_rows())
    msg = build_message(subject, plain, html_body=html)  # exposed test helper
    assert msg.is_multipart()
    parts = msg.get_payload()
    assert len(parts) == 2
    assert parts[0].get_content_type() == 'text/plain'
    assert parts[1].get_content_type() == 'text/html'

def test_send_email_html_body_param_backward_compat():
    """send_email(s, b) without html_body still sends plain MIMEText."""
    ...

def test_send_email_with_attachment_builds_mixed_multipart():
    """DA-CRIT-2: attachments parameter produces MIMEMultipart('mixed')."""
    ...
```

### 7.6 DST tests (DD-21)

```python
@pytest.mark.parametrize("test_date,expected_hour", [
    # Spring forward: March 9, 2025 (Sunday) — DST starts 02:00 ET
    ("2025-03-09T18:00:00", 18),  # weekly digest, 18:00 EDT after DST
    ("2025-03-10T07:30:00", 7),   # preopen, 07:30 EDT after DST
    # Fall back: November 2, 2025 (Sunday) — DST ends 02:00 ET
    ("2025-11-02T18:00:00", 18),  # weekly, 18:00 EST
    ("2025-11-03T07:30:00", 7),   # preopen, 07:30 EST
])
def test_digest_fires_at_correct_et_post_dst(test_date, expected_hour):
    """zoneinfo.ZoneInfo handles DST correctly — wall-clock 07:30/17:00/18:00."""
    ...
```

### 7.7 Crash-recovery + source_tag-match tests

```python
def test_in_progress_row_recovered_on_next_flush():
    """Manually mark queue row as 'in_progress' (simulating crash).
    Next flush_tier() picks it up via _recover_orphaned_in_progress."""
    ...

def test_dedup_key_prevents_double_send_on_restart():
    """Dispatcher succeeds, writes dedup row. Restart triggers re-flush.
    Second flush sees dedup row, skips dispatch."""
    ...

def test_concurrent_enqueue_during_flush_does_not_corrupt():
    """DA-MIN-17: 07:25 ET CRITICAL enqueues while 07:30 ET flush selects.
    Either enqueue commits before SELECT (appears in digest) or after (next flush)."""
    ...

def test_flush_with_source_tag_match_does_not_match_partial_word():
    """DA-MAJ-9: source_tag='email:preopened' is NOT claimed by match='email:preopen'."""
    ...

def test_flush_with_source_tag_match_matches_exact_and_subtag():
    """DA-MAJ-9: source_tag='email:preopen' AND 'email:preopen:critical-overflow'
    BOTH claimed by match='email:preopen'."""
    ...
```

### 7.8 Per-tier opt-out + empty suppression tests

```python
def test_preopen_disabled_skips_flush_but_enqueues():
    """config.email.tiers.preopen.enabled=false: enqueue() still works,
    flush_tier('preopen') returns early without calling send_email."""
    ...

def test_empty_preopen_tier_does_not_send_email():
    """DD-33: zero queued + zero critical replays → no email; dedup row written."""
    ...

def test_empty_postclose_tier_does_not_send_email():
    """DD-33."""
    ...

def test_empty_weekly_tier_still_sends_email_with_rolling_pnl():
    """DD-33: weekly's send_when_empty=true by default; renders rolling P&L."""
    ...
```

### 7.9 Hold-over mode tests (DA-CRIT-1 fix)

```python
def test_holdover_shadow_mode_writes_to_disk_not_email():
    """DA-CRIT-1: dual_write_hold_over.mode='shadow' → new path writes
    tmp/digest-shadow/preopen-2026-05-26.html; send_email NOT called."""
    ...

def test_holdover_shadow_mode_does_not_increase_inbox_count():
    """Operator inbox volume during hold-over UNCHANGED from current state.
    Test mocks SMTP; asserts send_email call-count for old paths only."""
    ...

def test_holdover_time_aligned_mode_suppresses_midday_and_evening():
    """mode='time_aligned' → premarket + EOD fire (old); midday + evening
    suppressed; new preopen + postclose fire from aggregator. Net 2 extra."""
    ...

def test_holdover_off_mode_only_new_path_fires():
    """mode='off' → only new aggregator fires."""
    ...

def test_old_path_enabled_legacy_flag_maps_to_mode():
    """Backward-compat: old_path_enabled=true → mode='shadow';
    old_path_enabled=false → mode='off'. Warning emitted."""
    ...
```

### 7.10 Handover-check tests (DA-MAJ-7 fix)

```python
def test_handover_check_passes_when_all_tripwires_pass():
    """Seed 7 days clean data → handover_check returns {'status': 'PASS', ...}."""
    ...

def test_handover_check_fails_on_abandoned_rows():
    """Seed an abandoned row in past 7 days → status='FAIL', reason='abandoned_rows_present'."""
    ...

def test_handover_check_fails_when_preopen_under_5_weekdays():
    """Seed only 4 days of preopen dedup rows → status='FAIL'."""
    ...

def test_compare_window_old_vs_new_rowid_inclusion():
    """DA-MAJ-11: every shadow_trade.id in old eod between Mon 16:15 and
    Tue 07:30 appears in NEW postclose Mon 17:00 OR new preopen Tue 07:30."""
    ...
```

### 7.11 Fallback + aggregator-failure tests (DA-MAJ-10 + DA-MIN-19 fix)

```python
def test_aggregator_import_error_falls_back_with_critical_log():
    """Patch import to ImportError → logger.critical called, send_email called,
    safe_send called (best-effort)."""
    ...

def test_aggregator_assertion_failure_is_not_swallowed_as_importerror():
    """Patch enqueue_for_email_digest to raise AssertionError → propagates;
    NOT caught by the ImportError handler in the caller."""
    ...
```

### 7.12 Test fixture pattern (per existing conventions)

```python
# tests/notifications/test_email_digest_<*>.py — follow tests/notifications/test_digest_queue.py

def _make_conn():
    """In-memory sqlite with notifications_digest_queue + notifications_sent + notifications_dedup."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE notifications_digest_queue (
            id INTEGER PRIMARY KEY,
            event_type TEXT, severity TEXT, payload_json TEXT,
            source_tag TEXT DEFAULT 'unknown',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            flushed_at TIMESTAMP, flush_status TEXT DEFAULT 'pending',
            flush_attempts INTEGER DEFAULT 0, flush_error TEXT
        );
        CREATE TABLE notifications_sent (...);
        CREATE TABLE notifications_dedup (...);
        CREATE UNIQUE INDEX notifications_dedup_uniq ON notifications_dedup(event_type, dedup_key);
    """)
    return conn
```

---

## 8. Decisions Log (35 decisions)

### Operator-confirmed (from checkpoint phase)

| ID | Decision | Rationale |
|---|---|---|
| **DD-01** | Severity=critical audit alerts fire immediately AND ALSO appear in next pre-open digest (Hybrid) | Operator-selected at checkpoint. Preserves halt-response latency for critical events; preserves "zero signal loss" via replay summary. Worst case: 3 emails on a bad day. |
| **DD-02** | Use `notifications_digest_queue.source_tag` with prefix scheme `'email:<tier>'` | Zero schema migration. source_tag is already free-form (64-char). Filter at flush time. |
| **DD-03** | `send_email()` grows optional `html_body` parameter; MIMEMultipart('alternative') when provided. **REVISED**: also grows `attachments` parameter for overflow-file support (DA-CRIT-2 fix). | Backward-compat (default None → existing plain-text behavior). Gmail renders HTML. Attachments use MIMEMultipart('mixed'). |
| **DD-04** | Reuse existing `DigestQueue` primitive with parallel email-dispatcher | No new queue infrastructure. Reuses retry + crash-recovery + audit trail. |
| **DD-05 (revised)** | Truncation = top-K by severity + overflow rows are EITHER attached as plain-text file OR deferred to next tier — NEVER silently dropped (DA-CRIT-2 fix). Removed dashboard URL reference. | Preserves signal by ranking; attached file preserves discoverability with zero out-of-scope dependencies. Operator config flag `email.digest_truncation.overflow_strategy` chooses. |
| **DD-06** | SMTP failure handled via existing `mark_flush_failed` retry path (max 3 attempts → abandoned) | No new failure-mode infrastructure. Operator-recoverable via queue inspection. |
| **DD-07** | Per-tier opt-out via `email.tiers.{preopen,postclose,weekly}.enabled: bool`. Events still enqueue when disabled. | Preserves audit trail under "operator on vacation"; resumed flush drains backlog. |
| **DD-08** | Two-mechanism verification: coverage-matrix contract test + 1-week dual-write hold-over | Test catches code-level drift; hold-over catches operational drift in real Gmail rendering. |
| **DD-09** | Enqueue-on-event with tier-prefixed source_tag; scheduled flush by tier | Decouples emit from delivery. Late-binding tier reassignment supported. |
| **DD-10** | Existing `digest_times` keys retained as deprecated; new `tier_times` keys added with backward-compat mapping. Weekly format is `"DOW HH:MM"` (Sun/Mon/.../Sat). Invalid formats raise ValueError with remediation message. (DA-NIT-20 fix) | Operator can roll over without YAML migration; deprecation warning logs once. |
| **DD-11** | `email_mode` collapses to `{silent, digest}`; full_stream/daily_summary become digest aliases | Reduces config surface; CLI `--email` flags remain unaffected. |
| **DD-12** | Saturday CTO + Saturday training emails deprecated; content moves to Sunday weekly | 1-week dual-fire hold-over for safe transition. |
| **DD-13** | Operator-explicit CLI `--email` flags BYPASS consolidation, fire immediately | Operator's escape hatch. Service-layer detects via `via_cli: bool` kwarg. |
| **DD-14** | `_do_dispatch_escalated` continues firing immediate email | Telegram-down means email is the only remaining channel. |

### Architect-decided (per architect-autonomy directive 2026-05-26)

| ID | Decision | Rationale | Alternatives considered |
|---|---|---|---|
| **DD-15** | New module `src/notifications/email_digest.py` (not extension of `telegram.py`) | telegram.py is 2000 lines named after a channel; adding cross-channel aggregation there blurs separation | Extending telegram.py (rejected: increases module bloat, misleading name); putting in src/email/ (rejected: ties aggregation to send path) |
| **DD-16** | Coverage-matrix test is a **declarative dict comparison** (`EVENT_TO_TIER` vs `EXPECTED_EVENT_TO_TIER`) PLUS AST-based bypass-call enumeration (DA-MAJ-4 fix). | Faster to extend, single source of truth, fails loudly on drift. AST is platform-neutral (Windows + Linux), grep is not. | Test-fixture-per-event-type (rejected: 14+ test functions for what's fundamentally a contract check); parametrized test (acceptable, but dict diff is more readable on failure); grep-based bypass detection (rejected: Linux-only) |
| **DD-17 (revised)** | Pre-open digest discovers overnight CRITICAL via `notifications_digest_queue` lookback (queue rows are canonical — DA-CRIT-3 + DD-34). **Was**: notifications_sent lookback. **Now**: queue rows tagged `email:preopen:critical-overflow` are the source of truth. | Single source of truth eliminates dedup ambiguity. Queue rows already exist for retry/recovery; rendering reads them. notifications_sent stays as audit trail of immediate side. | notifications_sent lookback (rejected: dedup ambiguity with throttle-suppressed cases — DA-CRIT-3); separate "replay_pending" column (rejected: schema change); both (rejected: ambiguity) |
| **DD-18** | **NO inline charts in v1**. Body is HTML+plain text only. Re-evaluate post-launch. | Reduces dependency burden (no matplotlib/Pillow on render path); SVG charts require font fallback complexity in Gmail; numeric tables suffice for the data being summarized | matplotlib PNG inline via `cid:` (rejected: ~80MB pip dependency, font issues, marginal value); ASCII sparklines (rejected: ugly in HTML); QuickChart.io URL embed (rejected: external dependency, privacy) |
| **DD-19** | Per-section budget: 10 events default (configurable). Total body soft cap: 100KB. Hard cap enforced by truncate-with-overflow (DD-05 revised: attach OR defer, not drop). | Gmail clips at 102KB (well-documented); 100KB soft cap leaves headroom. Top-K-by-severity is the proven compression strategy. | Unlimited (rejected: Gmail clipping); fixed N events regardless of severity (rejected: high-severity could be truncated out); compression-by-summarization-LLM (rejected: latency, cost, non-deterministic) |
| **DD-20 (revised)** | Dual-write hold-over has THREE modes: `shadow` (default — new path writes to disk, NOT email), `time_aligned` (selective old-path suppression, only +2 emails/day during hold-over), `off` (production). Old `old_path_enabled` flag retained as deprecated alias. (DA-CRIT-1 fix) | Shadow mode does NOT increase operator inbox volume during the most-visible hold-over week. Operator inspects shadow files at leisure. | Original always-dual-fire approach (rejected: inbox volume INCREASES during operator's most-visible week — DA-CRIT-1); env-var (rejected: deviates from YAML pattern); both-fire-then-monitor without flag (rejected: no operator-side off-switch during incident) |
| **DD-21** | `flush_tier('preopen')` and `flush_tier('postclose')` consult `holidays.is_market_holiday()`. Weekly tier ignores holidays. Configurable via `email.holidays.skip_*_on_market_holidays`. | Reuses existing pattern in `_is_market_open()`. Operator may want to disable holiday-skip for operational debrief on long weekends — hence configurable. | Always skip (rejected: removes operator flexibility); never skip (rejected: holiday "EOD recap" is misleading); date-explicit allowlist (rejected: maintenance burden) |
| **DD-22** | CLI: `python -m src.main digest-preview --tier <name> [--pending]`. `--pending` lists row IDs + event_types without rendering body. PLUS new `digest-handover-check` CLI (DA-MAJ-7 fix). | Operator-debuggable; preview without dispatch; handover gate is concrete tripwire | Web endpoint (rejected: dashboard inbox view is OOS per requirements); REPL-only (rejected: poor UX) |
| **DD-23 (revised)** | **Test floor preservation strategy:** PR 1 net-adds ~85-95 tests (45 new + 50 compensation for digest_builder's tests deletion in PR 2). After PR 2 deletes digest_builder.py + its ~50 tests, floor stays >= 5388 (DA-MAJ-13 fix). Task 17 (revised) includes inventory step. | CI 5388 floor protected throughout transition AND through PR 2; no test-floor incident risk. | Delete old tests immediately (rejected: breaks 5388 floor); rewrite old tests in place (rejected: confusing review); skip-marker on old tests (rejected: hides regressions) |
| **DD-24** | **Aggregator's enqueue path bypasses the `_KNOWN_EVENT_TYPES` allowlist by adding new email-tier event types to `_EVENT_MAP`**. Stub notify_* functions raise NotImplementedError (these events never dispatch via Telegram — they're email-only). | Cleanest: avoids fork in DigestQueue.enqueue's validation logic; preserves single source of truth for what events the system handles. | Bypass allowlist for email rows (rejected: weakens the invariant); separate queue table (rejected: schema duplication); skip validation for source_tag startswith 'email:' (acceptable fallback, more invasive) |
| **DD-25** | **Service-layer callers (scan_service, recap_service, watchlist_service) get a `via_cli: bool = False` kwarg.** CLI sets True; scheduled scheduler sets False (default). **REVISED:** `via_cli=True` propagates to ALL internal helper functions in the service module (DA-MAJ-8 fix). | Matches the existing pattern of optional kwargs throughout the codebase; explicit beats magic. Propagation prevents nested-helper bypass of carve-out semantics. | Detect-from-call-stack (rejected: fragile, untestable); separate function signatures for CLI vs scheduled (rejected: code duplication); no propagation (rejected: helpers would silently bypass — DA-MAJ-8) |
| **DD-26** | **`DigestQueue.enqueue` allowlist extended via new email-tier event types** (`'audit_critical'`, `'audit_alert'`, `'audit_red_assessment'`, `'morning_watchlist'`, `'action_packet'`, `'eod_recap'`, `'premarket_content'`, `'midday_content'`, `'eod_content'`, `'evening_content'`, `'weekly_digest_content'`, `'saturday_training_report'`, `'saturday_cto_report'`, `'research_synthesis'`). Stub notify_* functions added to `_EVENT_MAP_MUTABLE` (line 1397-1448) that raise NotImplementedError. These events are routed only to email aggregator; never to Telegram. (F-MIN-3 line-cite fix.) | Lightest-touch: 1-line addition per event_type to `_EVENT_MAP_MUTABLE`; preserves the `_KNOWN_EVENT_TYPES` invariant. | Bypass allowlist for email rows (rejected: weakens type safety); separate event-type registry for email (rejected: dual sources of truth) |
| **DD-27** | **`flush_tier()` aggregates rows itself** (separate SELECT) rather than relying on `DigestQueue.flush()` per-row dispatcher pattern. Manual UPDATE for status transitions; INSERT to `notifications_dedup` for idempotency. Overflow rows preserved (DA-CRIT-2): NEVER marked sent if their content wasn't actually delivered. | Telegram dispatches per-row, but email digests aggregate N rows into 1 body. Adapting `DigestQueue.flush()` for batch-aggregation would invert its semantics. A separate aggregator inside `flush_tier()` is cleaner. Preserving overflow rows enforces zero signal loss. | Reuse `DigestQueue.flush(source_tag_match=...)` (rejected: dispatcher would need closure-state for aggregation, fragile); restructure DigestQueue.flush to support batches (rejected: invasive change for one use case); mark overflow rows sent (rejected: violates zero-signal-loss — DA-CRIT-2) |
| **DD-28** | **`enqueue_for_email_digest()` raises KeyError on unmapped event_type** (instead of silently routing to a "default" tier) | Forces every new email-bound event_type to be declared in `EVENT_TO_TIER`; the load-bearing invariant is enforced at runtime, not just by the contract test | Silent default tier (rejected: hides the routing decision); log+drop (rejected: violates "zero signal loss") |
| **DD-29** | **Module structure within `src/notifications/email_digest.py`:** flat module with `EVENT_TO_TIER` + 5 public functions (added `handover_check` — DA-MAJ-7) + private `_collect_*`, `_render_*`, `_dispatch_*` helpers. No class hierarchy. | Matches `policy.py` and `digest_queue.py` flat-module conventions; testable without instantiation | EmailDigestAggregator class (rejected: pure-function aggregation doesn't need state); abstract base class (rejected: over-engineering for 3 tiers) |
| **DD-30 (revised)** | **Aggregator-import-failure fallback in caller files**: try/except catches `(ImportError, ModuleNotFoundError)` ONLY — NOT AssertionError. On catch: logger.critical with "FIREHOSE FALLBACK MODE" marker + best-effort Telegram alert + fall back to immediate send_email. (DA-MAJ-10 + DA-MIN-19 fix). | Loud failure mode prevents silent regression to firehose. AssertionError propagates (assertion failure = real coverage gap that needs human fix, not silent firehose). | No fallback (rejected: partial-deploy risk); silent fallback (rejected: operator gets firehose with no notice — DA-MAJ-10); catch all Exception (rejected: would swallow AssertionError module-load drift — DA-MIN-19) |
| **DD-31 (revised)** | **The OLD 4-builder code in `src/email/digest_builder.py` stays intact until PR 2.** Shadow-mode (default DD-20) means NEW path writes to disk during hold-over; old path keeps delivering emails as today. PR 2 (separate) deletes `digest_builder.py` and its tests AFTER `digest-handover-check` returns PASS. | Reversibility during transition; small atomic deletion PR is easier to review. PR 2 is gated on a concrete tripwire (handover_check). | Refactor in place (rejected: rebuild while old still running risks breaking both); two-PR sequence with hold-over disabled in between (acceptable, but more flag-management) |
| **DD-32** | **`render_digest()` is pure** (data-in, body-out). All DB queries done in `_collect_<tier>_data()` helpers that take a db_path. Allows test injection of seeded data. | Mirrors digest_builder.py pattern (`_safe_fetchall` helpers + main function takes db_path); enables targeted unit tests | Render-with-direct-DB-access (rejected: hard to test deterministically) |

### Added in revision pass (post-review)

| ID | Decision | Rationale | Alternatives considered |
|---|---|---|---|
| **DD-33** | **Empty-tier digest suppression rule:** if `flush_tier(tier)` renders a body with zero events AND zero critical replays AND `tiers.<tier>.send_when_empty=false`, NO email is sent. Dedup row STILL written (tier marks complete). Default: preopen/postclose `send_when_empty=false`; weekly `send_when_empty=true`. (DA-MAJ-12 fix.) | Eliminates "no notable events" emails — exactly the noise pattern operator complained about. Weekly always sends because rolling-7-day P&L is operator's regular checkpoint. | Always send empty (rejected: re-introduces noise — operator pain unchanged); never suppress (rejected: same); operator-explicit override only (rejected: defaults matter; default-false is safer) |
| **DD-34** | **Hybrid CRITICAL single source of truth: queue rows are canonical for digest replay.** notifications_sent is audit-only and NOT read by digest renderer. Dedup rule: `WHERE source_tag = 'email:preopen:critical-overflow' AND flush_status IN ('pending', 'in_progress')`. (DA-CRIT-3 fix.) | Eliminates dedup ambiguity between throttled vs non-throttled vs both. notifications_sent stays canonical for audit ("what fired immediately"). Queue row stays canonical for replay ("what to include in next digest"). | notifications_sent canonical (rejected: throttle-suppressed cases produce no notifications_sent row but operator still wants the alert in digest — DA-CRIT-3); both canonical (rejected: dedup ambiguity); content-hash dedup across both (rejected: complexity) |
| **DD-35** | **DigestQueue source_tag match semantics: colon-delimited exact-or-prefix.** SQL: `(source_tag = ? OR source_tag LIKE ? || ':%')`. NOT `source_tag LIKE ? || '%'`. (DA-MAJ-9 fix.) | Prevents `email:preopen` filter from claiming `email:preopened` or `email:preopen2`. Colon-delimited sub-tags are the documented convention. | Pure prefix (rejected: overmatch — DA-MAJ-9); regex (rejected: SQL portability + injection surface); separate column for sub-tag (rejected: schema change) |

---

## 9. Migration / rollout plan

### 9.1 Sequencing

1. **PR 1 (this design's `/arcis:code` output) — Batches 0-5.** Lands the aggregator + bypass remediation + shadow-mode dual-write. `dual_write_hold_over.enabled=true`, `mode=shadow`. NEW path writes to `tmp/digest-shadow/<tier>-YYYY-MM-DD.{html,txt}`. OLD path emails as today. Operator observes shadow files for 1 week.
2. **PR 2 — Old-path retirement.** AFTER `digest-handover-check` returns PASS (DA-MAJ-7 fix): set `dual_write_hold_over.mode=off` in `settings.local.yaml`. Operator observes for 3 days. If clean: delete `src/email/digest_builder.py` and its tests; remove `dual_write_hold_over` config block; remove the old code paths in `_check_digest_schedule` (replaced by new `flush_tier` calls); update CHANGELOG.

### 9.2 Operator-facing checklist (for `docs/operator-guide.md`)

- After PR 1 deploy: confirm inbox volume UNCHANGED from before (shadow mode does not send new emails). Telegram still gets notifications as today.
- After PR 1 deploy + 1 day: inspect `tmp/digest-shadow/preopen-YYYY-MM-DD.html` — open in browser, verify rendering looks correct.
- After PR 1 deploy + 1 day: run `python -m src.main digest-preview --tier preopen --pending` and confirm queue is draining when expected.
- After PR 1 deploy + 7 days: run `python -m src.main digest-handover-check` — expect status=PASS.
- After PR 1 deploy + 7 days: run `python -m src.main digest-handover-check --compare-window 7d` to verify row-ID inclusion check (DA-MAJ-11): every shadow_trade.id in old eod between Mon 16:15 ET and Tue 07:30 ET appears in new postclose Mon 17:00 ET OR new preopen Tue 07:30 ET shadow files.
- Before PR 2 merge: `digest-handover-check` MUST return PASS (concrete tripwire — DA-MAJ-7).
- After PR 2 deploy: inbox volume DROPS from current ~6-10/day to ~2/day weekdays + 1/week.

### 9.3 Rollback plan

- **Within PR 1's life:** flip `dual_write_hold_over.mode=shadow` (default) — new path stays silent. OR flip `email.tiers.<tier>.enabled=false` to silence per-tier.
- **Within PR 1's life, full disable:** flip ALL `email.tiers.*.enabled=false` — new aggregator goes silent (events still enqueue for audit). Old path continues.
- **Emergency:** revert PR 1 via `git revert`; old `_check_digest_schedule` is intact and continues working

### 9.4 CHANGELOG entry (template)

```markdown
## [Unreleased]

### Changed
- **Email notifications consolidated** (#115). The previous 4-15 daily email firehose has been collapsed into 2 daily digests (Pre-Open 07:30 ET, Post-Close 17:00 ET) plus 1 Sunday weekly report at 18:00 ET. All event types route to exactly one tier per the routing matrix in `src/notifications/email_digest.py`.
- Severity=critical audit alerts continue to fire immediately AND are now also replayed in the next pre-open digest (Hybrid behavior per operator decision).
- Telegram-failure escalations and operator-explicit CLI `--email` flags continue firing immediately (carve-outs).
- `send_email()` now accepts optional `html_body` and `attachments` parameters for MIMEMultipart support. Backward-compatible.
- `DigestQueue.flush()` now accepts optional `source_tag_match` filter for per-tier draining (colon-delimited prefix).
- `email_mode` collapsed to `{silent, digest}`. `full_stream` and `daily_summary` deprecated; aliased to `digest` at load with warning.

### Added
- `src/notifications/email_digest.py` — new aggregator module
- CLI: `python -m src.main digest-preview --tier {preopen,postclose,weekly}`
- CLI: `python -m src.main digest-handover-check [--window-days N] [--compare-window 7d]` — handover-readiness tripwires
- YAML keys: `email.tier_times.{preopen,postclose,weekly}`, `email.tiers.{preopen,postclose,weekly}.{enabled,send_when_empty}`, `email.digest_truncation.{top_k_per_section,overflow_strategy}`, `email.holidays.skip_*_on_market_holidays`, `email.dual_write_hold_over.{enabled,mode,shadow_output_dir}`

### Deprecated
- `email.digest_times.{premarket,midday,eod,evening}` — use `email.tier_times.*` instead. Config loader emits warning on first load.
- `email.dual_write_hold_over.old_path_enabled` — replaced by `mode`. Backward-compat mapping retained with warning.
- Saturday CTO + training report emails — moved into Sunday weekly digest. Saturday emails removed in PR 2 after handover-check PASS.
- 4-builder pattern in `src/email/digest_builder.py` — removed in PR 2.

### Fixed
- 11 bypass call sites (was 10; +1 reports.py:246 per F-MAJ-1) that previously called `send_email()` directly, skipping the policy gate and digest queue, now route through `enqueue_for_email_digest()`.
- Dead-code duplicate `run_saturday_reports` in `src/scheduler/reports.py:177-250` removed (was shadowed by `overnight.run_saturday_reports`; the reports.py copy was unreachable).

```

### 9.5 Hold-over exit criteria (DA-MAJ-7 fix)

PR 2 merge is gated on `digest-handover-check` returning PASS. The check verifies:

1. **Zero abandoned rows** in `notifications_digest_queue` where `source_tag LIKE 'email:%'` in past 7 days
2. **Preopen tier flushed >= 5 weekdays** of expected weekdays in past 7 days (one shadow file per weekday in `tmp/digest-shadow/preopen-*.html`)
3. **Postclose tier flushed >= 5 weekdays** in past 7 days
4. **Weekly tier flushed exactly once** in past 7 days (one shadow file `tmp/digest-shadow/weekly-*.html` in past Sunday's date range)
5. **Zero operator-reported missing-signal incidents** (operator's responsibility to clear; check is a placeholder for operator confirmation)
6. **Optional `--compare-window 7d`**: every shadow_trade.id mentioned in old eod between Mon 16:15 ET and Tue 07:30 ET appears in NEW postclose Mon 17:00 ET shadow file OR NEW preopen Tue 07:30 ET shadow file (row-ID inclusion check, DA-MAJ-11)

The CLI prints PASS/FAIL + per-tripwire details. Tying PR 2 merge to this CLI's PASS output is a concrete operator gate (no subjective "looks fine" judgment).

---

## 10. Risks + Open Issues

| Risk | Mitigation |
|---|---|
| Aggregator drops events silently during deploy | DD-30 (revised) try/except fallback with CRITICAL log + Telegram alert; coverage-matrix + bypass-AST tests |
| Postclose digest sent before all 17:00 ET events have arrived | Acceptable: events arriving after 17:00 ET roll into next preopen (07:30 next weekday). Carve-outs cover urgent. |
| Gmail's 102KB clip limit hit by long digests | DD-19: 100KB soft cap + top-K truncation + overflow attached as file or deferred (DD-05 revised) |
| DST transition causes off-by-hour delivery | DD-21 tests; stdlib zoneinfo handles transparently |
| Saturday→Sunday transition loses a week's training report data | Shadow-mode hold-over (DD-20 revised); compare-window CLI verifies row-ID inclusion |
| 24h auditor throttle conflicts with hybrid replay | DD-34: queue row is canonical, independent of throttle gate. Throttle-suppressed CRITICALs still appear in digest. |
| `dual_write_hold_over.mode` accidentally left on `shadow` permanently | CHANGELOG line item + operator-guide checklist + PR 2 explicitly flips to `off`; handover-check tripwire forces operator action |
| Tests deviate from existing fixture conventions, increasing review burden | Section 7.12 enumerates the exact fixture pattern; tasks reference it |
| Operator's pain unchanged ("still feels like too many") even at 2+1 | DA-MIN-14: measurement step in Section 9.2 — handover-check captures inbox count; operator can lobby for 1+1 or fold preopen into postclose in v+2 |

---

## 11. Known Considerations (informational, non-blocking)

Minor + nit findings from review, noted here for traceability. None require code changes in this revision pass.

- **DA-MIN-14 — operator perception of 2+1 cadence:** the consolidation may not fully solve operator pain if even 2/day weekday emails retain the skim-and-ignore habit. Section 9.2 captures inbox-count measurement; operator can decide post-deploy whether to further reduce (e.g., fold preopen into postclose).
- **DA-MIN-15 — "summarize" format for Hybrid CRITICAL replay:** the digest body for replayed criticals uses the format: `[ALREADY FIRED HH:MM ET] {category}: {description (truncated 300 chars)} — Recommendation: {recommendation (truncated 300 chars)}`. Defined here for implementer guidance.
- **DA-MIN-16 — source_tag length convention:** colon-delimited segments, each ≤ 24 chars, total ≤ 64 chars. Validated at enqueue: `assert len(source_tag) <= 64`. Documented in Section 3.2.
- **DA-MIN-17 — 07:25 ET CRITICAL race with 07:30 flush:** handled via IMMEDIATE-level transaction isolation (Section 6.2) + defensive payload field defaults (`payload.get(..., '')` everywhere). Test `test_concurrent_enqueue_during_flush_does_not_corrupt`.
- **DA-MIN-18 — subject format for zero values:** `'Arcis Pre-Open — {Mon DD} | {N} alerts, {M} watchlist'` where N=0 or M=0 renders as `'... | 0 alerts, 0 watchlist'` (literal zero shown, not omitted). Empty-tier suppression (DD-33) means this subject doesn't ship unless override.
- **DA-MIN-19 — module-load assert vs ImportError:** handled in DD-30 (revised). The email_digest.py module-load drift check uses `raise ImportError(...)` (not bare `assert`) so callers' try/except catch it. AssertionError in render code still propagates loudly.
- **DA-NIT-20 — `"Sun 18:00"` parser:** documented in YAML comment (Section 4.5) + DD-10 (revised). Format spec: `"<DOW> <HH:MM>"` where DOW ∈ {Sun/Mon/Tue/Wed/Thu/Fri/Sat} (case-insensitive) and HH:MM is 24-hour. Invalid format raises ValueError at config load with remediation message.
- **DA-NIT-21 — bypass-site count clarity:** resolved in Section 5.3 — full enumeration of all 20 (file, line, function) tuples with action per site. The "discrepancy" was 10 LIVE bypass sites + 2 dead (deleted) + 3 carve-outs + 4 legacy digest branches in watch.py (counted separately in some places). Section 5.3 reconciles.

---

## 12. References

- Codebase deep analysis: `tmp/deep_analysis_115.txt`
- Surface scan (15-email inventory): captured in this design's Section 5 routing matrix
- Root CLAUDE.md: schema discipline (all DDL in registry.py), test floor 5388
- Existing primitives: `src/notifications/digest_queue.py`, `src/notifications/policy.py`, `src/notifications/telegram.py:1397-1448` (event-map; F-MIN-3 fix)
- Existing config: `config/settings.local.yaml` lines 5-19 (email) + 251-271 (notifications)
- Existing call sites (grep-confirmed CALL lines): see Section 5.3 routing matrix for the 20 (file, line, function) tuples
- Existing test fixtures: `tests/notifications/test_digest_queue.py:15-51`, `tests/email/test_notifier.py:44-58`
- Review pass: feasibility findings (F-MAJ-1, F-MIN-1..5) + devil's advocate findings (DA-CRIT-1..3, DA-MAJ-4..13, DA-MIN-14..21). Resolution recorded in `revision_summary` (output) and inline citations throughout this spec.

