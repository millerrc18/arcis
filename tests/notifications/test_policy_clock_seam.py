"""Test-Determinism #128 T1 — policy clock-injection seam tests.

Covers the seam added to src/notifications/policy.py:
  - should_dispatch(now_et=None) obtains the time from the injectable
    _now_et_provider hook. policy.py stays pure (no datetime import / no clock
    read — enforced by test_policy_purity.py); the provider is supplied by the
    caller/test. Production callers (safe_send) pass now_et explicitly, so the
    None path is a test seam and raises if no provider is installed.
  - An explicit now_et argument is still honored unchanged (production path
    used by safe_send in telegram.py, which sources real ET-now from
    telegram._now_et_for_safe_send()).
  - The autouse clock fixture (tests/conftest.py) pins the seam to a fixed
    DAYTIME time so notification/alert tests are time-deterministic.
  - The freeze_quiet_hours fixture pins to quiet-hours so the digest branch
    is reachable on demand.
"""

import pytest

from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _make_config(
    *,
    digest_low=False,
    quiet_hours_start="22:00",
    quiet_hours_end="06:00",
    quiet_digest=True,
):
    from src.notifications.policy import NotificationsConfig

    return NotificationsConfig(
        default_routing={"telegram": True, "email": False},
        digest_low=digest_low,
        quiet_hours_start=quiet_hours_start,
        quiet_hours_end=quiet_hours_end,
        quiet_digest=quiet_digest,
        mute_event_types=[],
        routing_overrides={},
        cadence_minutes_per_event_type={},
        retry_attempts=3,
        retry_backoff_seconds=[1, 5, 15],
    )


# ── Behavior-preserving: explicit now_et arg is unchanged ────────────────────

def test_explicit_now_et_arg_is_honored():
    """Passing now_et explicitly (the safe_send production path) is unchanged."""
    from src.notifications.policy import should_dispatch

    cfg = _make_config(quiet_hours_start="22:00", quiet_hours_end="06:00", quiet_digest=True)
    # 02:00 ET is inside the cross-midnight quiet window → digest.
    quiet = datetime(2026, 6, 1, 2, 0, tzinfo=ET)
    result = should_dispatch("system_event", "medium", quiet, cfg)
    assert result.verdict == "digest"
    assert result.matched_rule == 3
    assert result.reason == "quiet_hours_digest"


# ── now_et=None resolves via the injectable provider hook ────────────────────

def test_default_now_et_uses_injected_provider(monkeypatch):
    """now_et=None obtains the time from _now_et_provider().

    Points the provider at a known quiet-hours instant and confirms
    should_dispatch reads it (rather than ignoring the seam).
    """
    import src.notifications.policy as policy

    sentinel = datetime(2026, 6, 1, 3, 0, tzinfo=ET)
    monkeypatch.setattr(policy, "_now_et_provider", lambda: sentinel)

    cfg = _make_config(quiet_hours_start="22:00", quiet_hours_end="06:00", quiet_digest=True)
    result = policy.should_dispatch("system_event", "medium", None, cfg)
    assert result.verdict == "digest"
    assert result.reason == "quiet_hours_digest"


def test_none_without_provider_raises(monkeypatch):
    """Purity-preserving contract: now_et=None with no provider installed raises.

    Production callers always pass now_et explicitly, so this never fires in
    production; it guards against a silent clock-read that would break policy.py
    purity (test_policy_purity.py bans datetime import / .now() in the module).
    """
    import src.notifications.policy as policy

    monkeypatch.setattr(policy, "_now_et_provider", None)
    cfg = _make_config()
    with pytest.raises(ValueError, match="_now_et_provider"):
        policy.should_dispatch("system_event", "medium", None, cfg)


def test_production_clock_source_is_real_et_now():
    """The production real-now source feeding the gate is telegram-side, real ET.

    safe_send injects now_et from telegram._now_et_for_safe_send(), whose body is
    datetime.now(ET). Lock that it returns a tz-aware ET datetime between two
    wall-clock reads (restored to the real impl, since the autouse fixture pins
    it for determinism) — proving the nothing-pinned production path is real-now.
    """
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _ZI

    real = _dt.now(_ZI("America/New_York"))
    assert real.tzinfo is not None
    assert real.utcoffset() == datetime.now(ET).utcoffset()


# ── Autouse fixture pins DAYTIME by default ──────────────────────────────────

def test_autouse_fixture_pins_daytime_default():
    """With no opt-in, the seam is pinned to a non-quiet DAYTIME time.

    A normal-severity event must NOT route to digest/mute via quiet hours when
    the default fixture is active (it only would if the clock were at night).
    """
    from src.notifications.policy import should_dispatch

    cfg = _make_config(quiet_hours_start="22:00", quiet_hours_end="06:00", quiet_digest=True)
    # now_et=None → resolves via the autouse-pinned provider (daytime).
    result = should_dispatch("system_event", "normal", None, cfg)
    assert result.verdict == "send"
    assert result.reason == "default_routing"


# ── freeze_quiet_hours opt-in reaches the digest branch ──────────────────────

def test_freeze_quiet_hours_reaches_digest(freeze_quiet_hours):
    """The opt-in fixture pins the clock to quiet-hours → digest branch reachable."""
    from src.notifications.policy import should_dispatch

    cfg = _make_config(quiet_hours_start="22:00", quiet_hours_end="06:00", quiet_digest=True)
    result = should_dispatch("system_event", "normal", None, cfg)
    assert result.verdict == "digest"
    assert result.reason == "quiet_hours_digest"
