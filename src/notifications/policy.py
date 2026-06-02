"""Notification routing policy gate (T10 Sprint 5 Wave D D1).

Called by: (none yet — T12 D3 will wire safe_send to consult this)
Calls: none
Owns tables: none
Config keys: notifications.*
Tests: tests/notifications/test_policy.py, tests/notifications/test_policy_purity.py

Pure-function gate: no I/O, no logging, no datetime.utcnow().
now_et is normally injected by the caller. As of Test-Determinism #128 T1,
should_dispatch also accepts now_et=None: the time is then obtained from the
injectable module-level hook _now_et_provider (a callable returning an ET
datetime). This module stays pure — it never imports datetime nor reads the
clock itself; the provider is supplied by the caller/test. Production always
injects now_et (safe_send passes telegram._now_et_for_safe_send()), so the
None path is a test seam. tests/conftest.py pins _now_et_provider for
time-deterministic notification tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Optional

# Injectable clock seam (#128 T1). Left None in production: every production
# caller (safe_send) injects now_et explicitly, so should_dispatch never reads
# this. Tests set it (tests/conftest.py autouse fixture) to pin the clock.
# Keeping it None preserves the module's purity contract (no datetime import,
# no .now() call here — enforced by tests/notifications/test_policy_purity.py).
_now_et_provider: Optional[Callable[[], "object"]] = None


@dataclass(frozen=True)
class NotificationsConfig:
    default_routing: dict
    digest_low: bool
    quiet_hours_start: str
    quiet_hours_end: str
    quiet_digest: bool
    mute_event_types: list
    routing_overrides: dict
    cadence_minutes_per_event_type: dict
    retry_attempts: int
    retry_backoff_seconds: list
    digest_flush_minutes: int = 60


@dataclass(frozen=True)
class PolicyDecision:
    verdict: Literal["send", "mute", "digest", "escalate"]
    reason: str
    channels: list
    matched_rule: int


def _parse_hhmm(s: str):
    parts = s.split(":")
    if len(parts) != 2:
        raise ValueError(f"Bad HH:MM: {s!r}")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Out of range HH:MM: {s!r}")
    return (h, m)


def _in_quiet_window(now_hm: tuple, start_hm: tuple, end_hm: tuple) -> bool:
    if start_hm == end_hm:
        return False
    if start_hm < end_hm:
        return start_hm <= now_hm <= end_hm
    return now_hm >= start_hm or now_hm <= end_hm


def _resolve_channels(event_type: str, config: NotificationsConfig) -> list:
    override = config.routing_overrides.get(event_type)
    if override:
        routing = {k: v for k, v in override.items() if k in ("telegram", "email")}
    else:
        routing = config.default_routing
    return [ch for ch in ("telegram", "email") if routing.get(ch)]


def should_dispatch(
    event_type: str,
    severity: str,
    now_et,
    config: NotificationsConfig,
) -> PolicyDecision:
    """Pure-function notification routing decision.

    Decision rules (FIRST MATCH WINS):
    1. severity in {'high', 'critical'} → SEND (always; rule #1 IS the bypass per Decision 20)
    2. event_type in config.mute_event_types → MUTE
    3. now_et within config.quiet_hours window:
       - if config.quiet_digest=True → DIGEST
       - else → MUTE
    4. severity == 'low' AND config.digest_low=True → DIGEST
    5. fallback → SEND via config.default_routing channels

    now_et: the ET datetime to evaluate quiet hours against. Pass None to obtain
    it from the injectable _now_et_provider hook (#128 T1). Production callers
    (safe_send) always pass now_et explicitly and are unaffected; the None path
    is a test seam and raises if no provider is installed.
    """
    if now_et is None:
        if _now_et_provider is None:
            raise ValueError(
                "should_dispatch(now_et=None) requires _now_et_provider to be "
                "set (test seam, #128 T1); production callers must pass now_et."
            )
        now_et = _now_et_provider()

    # Rule 1: high/critical severity always sends
    if severity in ("high", "critical"):
        return PolicyDecision(
            verdict="send",
            reason="high_severity_bypass",
            channels=_resolve_channels(event_type, config),
            matched_rule=1,
        )

    # Rule 2: event_type in mute list
    if event_type in config.mute_event_types:
        return PolicyDecision(
            verdict="mute",
            reason="event_type_muted",
            channels=[],
            matched_rule=2,
        )

    # Rule 3: quiet hours
    start_hm = _parse_hhmm(config.quiet_hours_start)
    end_hm = _parse_hhmm(config.quiet_hours_end)
    now_hm = (now_et.hour, now_et.minute)
    if _in_quiet_window(now_hm, start_hm, end_hm):
        if config.quiet_digest:
            return PolicyDecision(
                verdict="digest",
                reason="quiet_hours_digest",
                channels=[],
                matched_rule=3,
            )
        return PolicyDecision(
            verdict="mute",
            reason="quiet_hours_mute",
            channels=[],
            matched_rule=3,
        )

    # Rule 4: low severity + digest_low
    if severity == "low" and config.digest_low:
        return PolicyDecision(
            verdict="digest",
            reason="low_severity_digest",
            channels=[],
            matched_rule=4,
        )

    # Rule 5: default routing
    return PolicyDecision(
        verdict="send",
        reason="default_routing",
        channels=_resolve_channels(event_type, config),
        matched_rule=5,
    )
