"""T4 (Sprint #115 Email Consolidation, Batch 1): event_map allowlist tests.

Validates that the 14 email-tier event_types are registered in
``_EVENT_MAP_MUTABLE`` so that ``DigestQueue.enqueue`` (which checks
``_KNOWN_EVENT_TYPES``) accepts them. The registered stubs MUST raise
``NotImplementedError`` because email-tier events are never dispatched via
Telegram — they flow through ``src.notifications.email_digest.flush_tier``.

DD-24 + DD-26 of docs/audits/2026-05-26-email-consolidation/specs/.
"""

import pytest


EMAIL_TIER_NAMES = (
    "audit_critical",
    "audit_alert",
    "audit_red_assessment",
    "morning_watchlist",
    "action_packet",
    "eod_recap_email",
    "premarket_content",
    "midday_content",
    "eod_content",
    "evening_content",
    "weekly_digest_content",
    "saturday_training_report",
    "saturday_cto_report",
    "research_synthesis_email",
)


def test_email_tier_events_in_event_map():
    """All 14 email-tier event_types are keys in _EVENT_MAP / _EVENT_MAP_MUTABLE."""
    from src.notifications.telegram import _EVENT_MAP, _EVENT_MAP_MUTABLE

    for name in EMAIL_TIER_NAMES:
        assert name in _EVENT_MAP_MUTABLE, (
            f"email-tier event {name!r} missing from _EVENT_MAP_MUTABLE"
        )
        assert name in _EVENT_MAP, (
            f"email-tier event {name!r} missing from _EVENT_MAP"
        )


@pytest.mark.parametrize("event_name", EMAIL_TIER_NAMES)
def test_email_tier_stub_raises_not_implemented(event_name):
    """Each stub raises NotImplementedError with the documented dispatcher message."""
    from src.notifications import telegram as _tg

    stub_name = f"notify_{event_name}_email_only"
    stub = getattr(_tg, stub_name, None)
    assert stub is not None, f"stub function {stub_name} not defined"

    with pytest.raises(NotImplementedError) as exc_info:
        stub()

    msg = str(exc_info.value)
    assert event_name in msg, (
        f"NotImplementedError message must contain event name {event_name!r}; got: {msg!r}"
    )
    assert "email_digest.flush_tier" in msg, (
        f"NotImplementedError message must reference 'email_digest.flush_tier'; got: {msg!r}"
    )


def test_email_tier_stub_raises_with_args_kwargs():
    """Stubs accept *args/**kwargs (allowlist callsites need not match a fixed signature)."""
    from src.notifications.telegram import notify_audit_critical_email_only

    with pytest.raises(NotImplementedError):
        notify_audit_critical_email_only("some_arg", another=42)


def test_known_event_types_includes_email_tier():
    """_KNOWN_EVENT_TYPES frozenset rebuilt from _EVENT_MAP includes all 14 names."""
    from src.notifications.telegram import _KNOWN_EVENT_TYPES

    for name in EMAIL_TIER_NAMES:
        assert name in _KNOWN_EVENT_TYPES, (
            f"email-tier event {name!r} missing from _KNOWN_EVENT_TYPES "
            f"(should auto-derive from _EVENT_MAP)"
        )


def test_email_tier_event_types_constant_exported():
    """EMAIL_TIER_EVENT_TYPES is exported (no underscore prefix) and a frozenset."""
    from src.notifications import telegram as _tg

    assert hasattr(_tg, "EMAIL_TIER_EVENT_TYPES"), (
        "EMAIL_TIER_EVENT_TYPES constant must be defined in telegram module"
    )
    constant = _tg.EMAIL_TIER_EVENT_TYPES
    assert isinstance(constant, frozenset), (
        f"EMAIL_TIER_EVENT_TYPES must be a frozenset; got {type(constant).__name__}"
    )
    assert set(constant) == set(EMAIL_TIER_NAMES), (
        f"EMAIL_TIER_EVENT_TYPES must contain exactly the 14 names; "
        f"got {sorted(constant)}"
    )


def test_email_tier_constant_subset_of_known_event_types():
    """EMAIL_TIER_EVENT_TYPES ⊆ _KNOWN_EVENT_TYPES — guards Task 5 import contract."""
    from src.notifications.telegram import (
        EMAIL_TIER_EVENT_TYPES,
        _KNOWN_EVENT_TYPES,
    )

    assert EMAIL_TIER_EVENT_TYPES <= _KNOWN_EVENT_TYPES, (
        "EMAIL_TIER_EVENT_TYPES must be a subset of _KNOWN_EVENT_TYPES"
    )


def test_existing_telegram_events_unchanged():
    """High-value pre-existing event_types must still be present (no deletion regression)."""
    from src.notifications.telegram import _EVENT_MAP

    # Sample of pre-existing event_types covering each category in _EVENT_MAP_MUTABLE.
    must_exist = {
        # Trade lifecycle
        "trade_opened",
        "trade_closed",
        # Scan & pipeline
        "scan_complete",
        "scan_result",
        "first_scan_summary",
        "watchlist",
        "premarket_complete",
        "premarket_brief",
        # System & risk alerts
        "risk_alert",
        "system_event",
        "startup_complete",
        "validation_summary",
        "collection_failure",
        "exposure_alert",
        "regime_alert",
        # Overnight & scheduling
        "overnight_complete",
        "overnight_training_complete",
        "gpu_health",
        "scoring_summary",
        "schedule_health",
        # Periodic reports
        "daily_summary",
        "eod_report",
        "data_asset_report",
        "weekly_digest",
        "retrain_report",
        "research_papers",
        "research_digest",
        # Milestones & alerts
        "milestone",
        "streak_alert",
        "earnings_warning",
        "position_earnings_warning",
        "model_event",
        # Action reminders
        "action_required",
        # Training & data
        "trainer_holdout_empty",
        "1min_bar_collection",
        "attribution_resolve_complete",
        "stress_test_complete",
        "trading_stats_update",
        # Monitoring (Wave C T4)
        "manual_intervention_drift",
        # Monitoring (Wave D T14 D5)
        "alert_silence",
    }
    missing = must_exist - set(_EVENT_MAP.keys())
    assert not missing, f"pre-existing event_types deleted by T4: {sorted(missing)}"
    # Sanity: pre-T4 baseline holds 40 event_types (brief said 39 — actual was 40).
    assert len(must_exist) == 40, (
        f"baseline must_exist set should hold 40 names; has {len(must_exist)}"
    )


def test_email_tier_count_is_fourteen():
    """Spec-mandated count: exactly 14 email-tier event_types."""
    from src.notifications.telegram import EMAIL_TIER_EVENT_TYPES

    assert len(EMAIL_TIER_EVENT_TYPES) == 14, (
        f"spec requires exactly 14 email-tier event_types; got {len(EMAIL_TIER_EVENT_TYPES)}"
    )
