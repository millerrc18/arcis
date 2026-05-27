"""Tests for the email-tier config consolidation (Sprint #115, Task 1).

Spec: docs/audits/2026-05-26-email-consolidation/specs/2026-05-26-email-consolidation-design.md
Plan: docs/audits/2026-05-26-email-consolidation/plans/2026-05-26-email-consolidation.md

These tests pin the new YAML schema introduced for the 4-15 emails/weekday →
3-digests/week consolidation:

  - email.tier_times.{preopen,postclose,weekly}        (DD-10)
  - email.tiers.{preopen,postclose,weekly}.{enabled, send_when_empty}  (DD-07, DD-33)
  - email.digest_truncation.{top_k_per_section, overflow_strategy, overflow_attach_format}
  - email.holidays.{skip_preopen_on_market_holidays, skip_postclose_on_market_holidays}
  - email.dual_write_hold_over.{enabled, mode, shadow_output_dir, old_path_enabled}  (DD-20 revised)

Plus the deprecation-warning machinery in load_config() that emits one
warning-per-process for:

  - legacy email.digest_times.* keys
  - legacy bootcamp.email_mode in {'full_stream', 'daily_summary'}
  - legacy dual_write_hold_over.old_path_enabled flag

And the weekly tier-time parser exposed for use by Task 5's scheduler.
"""

from __future__ import annotations

import pytest
import yaml


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point load_config() at a tmp config dir and clear the cache.

    Returns a helper that writes a YAML dict to settings.local.yaml inside
    the tmp dir, resets the loader cache, and returns the freshly loaded
    config dict. Uses ARCIS_CONFIG_DIR env-var override to redirect the
    loader without re-importing the module (which would re-run side
    effects like load_dotenv()).
    """
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()

    monkeypatch.setenv("ARCIS_CONFIG_DIR", str(cfg_dir))

    import src.config as cfg_mod

    # Reset the once-per-process deprecation sentinels so each test starts
    # clean. We must restore them on teardown to avoid bleed-through (e.g.
    # subsequent tests' warning expectations being polluted).
    saved_email = cfg_mod._email_deprecation_warning_emitted
    saved_bootcamp = cfg_mod._bootcamp_email_mode_warning_emitted
    saved_old_path = cfg_mod._old_path_enabled_warning_emitted
    cfg_mod._email_deprecation_warning_emitted = False
    cfg_mod._bootcamp_email_mode_warning_emitted = False
    cfg_mod._old_path_enabled_warning_emitted = False

    def _write_and_load(yaml_dict: dict) -> dict:
        local_path = cfg_dir / "settings.local.yaml"
        local_path.write_text(yaml.safe_dump(yaml_dict), encoding="utf-8")
        return cfg_mod.reload_config()

    yield _write_and_load

    # Restore sentinels + clear the cache so the next test gets a clean
    # loader state (no stale config dict from this test's tmp dir).
    cfg_mod._email_deprecation_warning_emitted = saved_email
    cfg_mod._bootcamp_email_mode_warning_emitted = saved_bootcamp
    cfg_mod._old_path_enabled_warning_emitted = saved_old_path
    cfg_mod._config_cache = None


# ──────────────────────────────────────────────────────────────────────
# (a) Deprecated digest_times maps to tier_times
# ──────────────────────────────────────────────────────────────────────


def test_deprecated_digest_times_maps_to_tier_times(isolated_config, caplog):
    """Old digest_times keys present + no new tier_times keys → loader
    fills tier_times.preopen from digest_times.premarket and
    tier_times.postclose from digest_times.eod, emitting ONE warning."""
    import logging
    caplog.set_level(logging.WARNING, logger="src.config")

    cfg = isolated_config({
        "email": {
            "digest_times": {
                "premarket": "07:45",
                "midday": "12:00",
                "eod": "16:20",
                "evening": "20:00",
            },
        },
    })

    tier_times = cfg["email"]["tier_times"]
    assert tier_times["preopen"] == "07:45", (
        f"expected preopen mapped from premarket=07:45, got {tier_times!r}"
    )
    assert tier_times["postclose"] == "16:20", (
        f"expected postclose mapped from eod=16:20, got {tier_times!r}"
    )

    # Deprecation warning emitted exactly once for the email block
    email_warnings = [
        rec for rec in caplog.records
        if "digest_times" in rec.message and "deprecated" in rec.message.lower()
    ]
    assert len(email_warnings) == 1, (
        f"expected exactly one digest_times deprecation warning, "
        f"got {len(email_warnings)}: {[r.message for r in email_warnings]}"
    )


def test_deprecated_digest_times_warning_fires_only_once(isolated_config, caplog):
    """Re-loading the same legacy YAML twice in-process emits ONLY ONE
    warning (sentinel-guarded per src/email/notifier.py:21,75 pattern)."""
    import logging
    caplog.set_level(logging.WARNING, logger="src.config")

    legacy = {"email": {"digest_times": {"premarket": "07:30", "eod": "16:15"}}}
    isolated_config(legacy)

    first_load_warnings = [
        rec for rec in caplog.records
        if "digest_times" in rec.message and "deprecated" in rec.message.lower()
    ]
    assert len(first_load_warnings) == 1, (
        "first load must fire the deprecation warning (otherwise this "
        f"once-per-process test is vacuous), got {len(first_load_warnings)}"
    )

    caplog.clear()
    # second reload of the same YAML → no NEW warning
    import src.config as cfg_mod
    cfg_mod.reload_config()

    email_warnings = [
        rec for rec in caplog.records
        if "digest_times" in rec.message and "deprecated" in rec.message.lower()
    ]
    assert len(email_warnings) == 0, (
        f"warning fired again on second load — should be once-per-process: "
        f"{[r.message for r in email_warnings]}"
    )


# ──────────────────────────────────────────────────────────────────────
# (b) bootcamp.email_mode aliases
# ──────────────────────────────────────────────────────────────────────


def test_email_mode_full_stream_aliased_to_digest(isolated_config, caplog):
    """bootcamp.email_mode='full_stream' loads as 'digest' + warning."""
    import logging
    caplog.set_level(logging.WARNING, logger="src.config")

    cfg = isolated_config({"bootcamp": {"email_mode": "full_stream"}})

    assert cfg["bootcamp"]["email_mode"] == "digest", (
        f"expected 'full_stream' aliased to 'digest', "
        f"got {cfg['bootcamp']['email_mode']!r}"
    )

    relevant = [
        rec for rec in caplog.records
        if "email_mode" in rec.message and "deprecated" in rec.message.lower()
    ]
    assert len(relevant) == 1, (
        f"expected one bootcamp.email_mode deprecation warning, "
        f"got {len(relevant)}: {[r.message for r in relevant]}"
    )


def test_email_mode_daily_summary_aliased_to_digest(isolated_config, caplog):
    """bootcamp.email_mode='daily_summary' also collapses to 'digest'."""
    import logging
    caplog.set_level(logging.WARNING, logger="src.config")

    cfg = isolated_config({"bootcamp": {"email_mode": "daily_summary"}})

    assert cfg["bootcamp"]["email_mode"] == "digest"


# ──────────────────────────────────────────────────────────────────────
# (c) 'silent' passthrough (unchanged)
# ──────────────────────────────────────────────────────────────────────


def test_email_mode_silent_passthrough(isolated_config, caplog):
    """'silent' is part of the new {silent, digest} set — unchanged + NO warning."""
    import logging
    caplog.set_level(logging.WARNING, logger="src.config")

    cfg = isolated_config({"bootcamp": {"email_mode": "silent"}})
    assert cfg["bootcamp"]["email_mode"] == "silent"

    relevant = [
        rec for rec in caplog.records
        if "email_mode" in rec.message and "deprecated" in rec.message.lower()
    ]
    assert relevant == [], (
        f"'silent' is the new vocabulary — must NOT warn. Got: "
        f"{[r.message for r in relevant]}"
    )


# ──────────────────────────────────────────────────────────────────────
# (d) New tier_times take precedence; no warning when only new keys
# ──────────────────────────────────────────────────────────────────────


def test_new_tier_times_take_precedence(isolated_config, caplog):
    """When BOTH old digest_times AND new tier_times are present, the new
    keys win and NO deprecation warning fires (operator is using the new
    vocabulary, the old keys are just lying around)."""
    import logging
    caplog.set_level(logging.WARNING, logger="src.config")

    cfg = isolated_config({
        "email": {
            "digest_times": {"premarket": "07:00", "eod": "15:00"},
            "tier_times": {
                "preopen": "07:30",
                "postclose": "17:00",
                "weekly": "Sun 18:00",
            },
        },
    })

    assert cfg["email"]["tier_times"]["preopen"] == "07:30"
    assert cfg["email"]["tier_times"]["postclose"] == "17:00"

    email_warnings = [
        rec for rec in caplog.records
        if "digest_times" in rec.message and "deprecated" in rec.message.lower()
    ]
    assert email_warnings == [], (
        "when tier_times already present, digest_times deprecation must NOT fire — "
        f"got {[r.message for r in email_warnings]}"
    )


# ──────────────────────────────────────────────────────────────────────
# (e) Hold-over mode default = 'shadow'
# ──────────────────────────────────────────────────────────────────────


def test_holdover_mode_shadow_default(isolated_config):
    """Fresh config with NO dual_write_hold_over block → mode defaults to
    'shadow' (DD-20 revised safest-default rule)."""
    cfg = isolated_config({"email": {"tier_times": {"preopen": "07:30"}}})
    mode = cfg["email"]["dual_write_hold_over"]["mode"]
    assert mode == "shadow", (
        f"DD-20 mandates mode='shadow' as the safest default, got {mode!r}"
    )


# ──────────────────────────────────────────────────────────────────────
# (f) old_path_enabled legacy → mode mapping + deprecation warning
# ──────────────────────────────────────────────────────────────────────


def test_old_path_enabled_legacy_maps_to_mode_shadow(isolated_config, caplog):
    """Legacy old_path_enabled=true → mode='shadow' + warning."""
    import logging
    caplog.set_level(logging.WARNING, logger="src.config")

    cfg = isolated_config({
        "email": {"dual_write_hold_over": {"old_path_enabled": True}}
    })
    assert cfg["email"]["dual_write_hold_over"]["mode"] == "shadow"

    matching = [
        rec for rec in caplog.records
        if "old_path_enabled" in rec.message and "deprecated" in rec.message.lower()
    ]
    assert len(matching) == 1, (
        f"expected one old_path_enabled deprecation warning, got {len(matching)}"
    )


def test_old_path_enabled_legacy_maps_to_mode_off(isolated_config, caplog):
    """Legacy old_path_enabled=false → mode='off' + warning."""
    import logging
    caplog.set_level(logging.WARNING, logger="src.config")

    cfg = isolated_config({
        "email": {"dual_write_hold_over": {"old_path_enabled": False}}
    })
    assert cfg["email"]["dual_write_hold_over"]["mode"] == "off"

    matching = [
        rec for rec in caplog.records
        if "old_path_enabled" in rec.message and "deprecated" in rec.message.lower()
    ]
    assert len(matching) == 1


def test_explicit_mode_overrides_old_path_enabled(isolated_config):
    """If BOTH explicit `mode` and legacy `old_path_enabled` are present,
    the explicit mode wins (operator is migrating: keep their intent)."""
    cfg = isolated_config({
        "email": {
            "dual_write_hold_over": {
                "mode": "off",
                "old_path_enabled": True,   # contradicts mode='off'
            }
        }
    })
    assert cfg["email"]["dual_write_hold_over"]["mode"] == "off", (
        "explicit mode must win over legacy old_path_enabled"
    )


# ──────────────────────────────────────────────────────────────────────
# (g) Weekly tier-time DOW parser — valid
# ──────────────────────────────────────────────────────────────────────


def test_weekly_tier_time_dow_parser_valid_sunday():
    """'Sun 18:00' parses to (weekday=6, hour=18, minute=0).

    Mon=0..Sun=6 follows datetime.weekday()."""
    from src.config import parse_weekly_tier_time
    assert parse_weekly_tier_time("Sun 18:00") == (6, 18, 0)


def test_weekly_tier_time_dow_parser_valid_case_insensitive():
    """DOW is case-insensitive per spec Section 4.5."""
    from src.config import parse_weekly_tier_time
    assert parse_weekly_tier_time("MON 09:30") == (0, 9, 30)
    assert parse_weekly_tier_time("sun 18:00") == (6, 18, 0)
    assert parse_weekly_tier_time("Fri 04:00") == (4, 4, 0)


def test_weekly_tier_time_dow_parser_valid_all_days():
    """All seven DOW abbreviations parse — Mon=0..Sun=6."""
    from src.config import parse_weekly_tier_time
    for i, dow in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
        wd, h, m = parse_weekly_tier_time(f"{dow} 09:00")
        assert wd == i, f"{dow} should be weekday {i}, got {wd}"
        assert h == 9 and m == 0


# ──────────────────────────────────────────────────────────────────────
# (h) Weekly tier-time DOW parser — invalid raises ValueError
# ──────────────────────────────────────────────────────────────────────


def test_weekly_tier_time_dow_parser_invalid_dow():
    """'Funday 18:00' → ValueError with remediation message."""
    from src.config import parse_weekly_tier_time
    with pytest.raises(ValueError) as exc:
        parse_weekly_tier_time("Funday 18:00")
    msg = str(exc.value)
    # Remediation must mention the legal DOW set so operator can fix it
    assert "Mon" in msg and "Sun" in msg, (
        f"ValueError remediation message must list legal DOW values, got: {msg!r}"
    )


def test_weekly_tier_time_dow_parser_invalid_time():
    """'Mon 25:99' → ValueError with remediation message."""
    from src.config import parse_weekly_tier_time
    with pytest.raises(ValueError) as exc:
        parse_weekly_tier_time("Mon 25:99")
    msg = str(exc.value)
    # Must mention valid time range so operator can fix it
    assert "HH:MM" in msg or "00-23" in msg or "00-59" in msg, (
        f"ValueError remediation must describe valid time ranges, got: {msg!r}"
    )


def test_weekly_tier_time_dow_parser_missing_time():
    """'Sun' (no time) → ValueError with remediation message."""
    from src.config import parse_weekly_tier_time
    with pytest.raises(ValueError) as exc:
        parse_weekly_tier_time("Sun")
    msg = str(exc.value)
    assert "HH:MM" in msg or "DOW" in msg.upper() or "format" in msg.lower(), (
        f"ValueError remediation must indicate the expected format, got: {msg!r}"
    )


def test_invalid_weekly_tier_time_raises_at_config_load(isolated_config):
    """If email.tier_times.weekly is malformed at load, ValueError is raised
    (vs. silently failing later at flush time)."""
    with pytest.raises(ValueError) as exc:
        isolated_config({
            "email": {"tier_times": {"weekly": "Funday 99:99"}}
        })
    assert "Funday" in str(exc.value) or "tier_times.weekly" in str(exc.value).lower()


# ──────────────────────────────────────────────────────────────────────
# (i) send_when_empty default per tier (DD-33)
# ──────────────────────────────────────────────────────────────────────


def test_send_when_empty_default_per_tier(isolated_config):
    """DD-33 defaults:
       preopen   send_when_empty=False
       postclose send_when_empty=False
       weekly    send_when_empty=True (rolling P&L always sends)
    """
    cfg = isolated_config({"email": {}})

    tiers = cfg["email"]["tiers"]
    assert tiers["preopen"]["send_when_empty"] is False, (
        f"preopen default must be False (DD-33), got {tiers['preopen']!r}"
    )
    assert tiers["postclose"]["send_when_empty"] is False, (
        f"postclose default must be False (DD-33), got {tiers['postclose']!r}"
    )
    assert tiers["weekly"]["send_when_empty"] is True, (
        f"weekly default must be True (DD-33), got {tiers['weekly']!r}"
    )


def test_send_when_empty_operator_override_preserved(isolated_config):
    """Operator override of send_when_empty must NOT be clobbered by defaults."""
    cfg = isolated_config({
        "email": {
            "tiers": {
                "preopen": {"send_when_empty": True},   # operator override
                "weekly": {"send_when_empty": False},   # operator override
            }
        }
    })

    tiers = cfg["email"]["tiers"]
    assert tiers["preopen"]["send_when_empty"] is True
    assert tiers["weekly"]["send_when_empty"] is False
