"""Configuration loader for the Systematic Equity Research.

Called by: api.routes.actions, api.routes.scan, api.routes.shadow, api.routes.system, cli.commands, data_collection.analyst_collector, data_collection.insider_collector, data_collection.macro_collector, data_collection.short_interest_collector, email.notifier, evaluation.auditor, evaluation.backtester, evaluation.cto_report, evaluation.system_validator, llm.client, llm.grammar_client, llm.postmortem_writer, main, notifications.telegram, packets.eod_recap, ranking.ranker, risk.governor, scheduler.premarket, scheduler.vram_manager, scheduler.watch, shadow_trading.alpaca_adapter, shadow_trading.executor, training.ab_evaluation, training.bootstrap, training.claude_client, training.data_collector, training.historical_scanner, training.trainer
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_config_tech_debt.py

Config loading precedence:
1. config/settings.local.yaml (gitignored, contains real API keys)
2. config/settings.example.yaml (checked in, placeholder values)

The config is cached after first load for performance — most modules import
load_config() at module level. Use reload_config() after writing to the
YAML file (e.g., from the /config PUT endpoint).

DB_PATH is a module-level constant (not in the YAML) because it's needed
before YAML loads (e.g., for schema validation at import time). Override
via ARCIS_DB_PATH env var for testing or multi-instance setups.

Env var precedence: Individual modules (telegram, collectors) check
os.environ FIRST, then fall back to YAML values. This lets Render set
tokens via env vars without duplicating them in the YAML file.

Known issue #132: If settings.local.yaml is missing, the system falls back to
settings.example.yaml which has placeholder API keys. The validate_config()
function detects common placeholder patterns and logs warnings, but doesn't
crash — this allows tests to run without real API keys.
"""

import logging
import os
import re
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Load .env file BEFORE any os.environ lookups. This ensures API keys
# in .env are available regardless of how the code is invoked (CLI,
# direct import, one-liner, etc.). Duplicate of the call in main.py
# and watch.py, but load_dotenv() is idempotent — safe to call multiple times.
#
# === Path-pinned to repo root (PA-4, 2026-05-15 RCCA) ===
# Default `load_dotenv()` calls `find_dotenv()` which walks UP from CWD
# looking for `.env`. When pytest runs in an agent worktree at
# C:/arcis/halcyon-lab/.claude/worktrees/agent-XXX/, it walks up to
# C:/arcis/halcyon-lab/ and inherits the operator's production `.env`
# — including DATABASE_URL=prod-PG + ARCIS_PG_CUTOVER_ENABLED=1. This
# defeats worktree env-isolation (memory `feedback_worktree_env_drift`
# was previously believed to be a one-way isolation; H5 finding in
# docs/audits/2026-05-14-p0-pg-wipe/rcca.md proved otherwise).
#
# Binding `dotenv_path` to <THIS-FILE>/../../.env (the SAME repo as
# this src/config/__init__.py) means:
#   - On the operator's main repo: same `.env` loaded as before.
#   - In an agent worktree: that worktree's own `.env` (typically
#     absent because `.env` is gitignored). Nothing inherited from
#     the parent repo. Worktree env-isolation is restored.
_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
if os.environ.get("ARCIS_DISABLE_DOTENV") != "1":
    load_dotenv(dotenv_path=_ENV_PATH, override=False)

# Central database path constant — must be set via ARCIS_DB_PATH env var.
# This is the single source of truth for the SQLite path. Every module
# imports DB_PATH from here rather than hardcoding the filename.
#
# Sprint 0 Wave 1d (DB-STUB-CFG, T6, cluster-02 Critical #1, 2026-04-26):
# Removed the repo-root stub fallback. CLAUDE.md mandate (#642) prohibits
# writes to <halcyon-lab>/ai_research_desk.sqlite3 — that location is a
# stub and was removed. The canonical path is C:/arcis/data/ai_research_desk.sqlite3
# and must be supplied via the ARCIS_DB_PATH env var (loaded from .env by
# the load_dotenv() call above). If the var is missing, fail fast rather
# than silently writing to the forbidden stub location.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DB_PATH_ENV = os.environ.get("ARCIS_DB_PATH")
_DATABASE_URL = os.environ.get("DATABASE_URL")
# Postgres-only deploys (Render) set DATABASE_URL but not ARCIS_DB_PATH —
# the SQLite path is irrelevant in that environment. Fail-fast only when
# BOTH are missing (genuine misconfiguration). Callers that read DB_PATH
# must guard with `if DB_PATH:` for cross-deploy safety.
if not _DB_PATH_ENV and not _DATABASE_URL:
    raise RuntimeError(
        "ARCIS_DB_PATH not set and DATABASE_URL not set; one is required. "
        "For local SQLite, set ARCIS_DB_PATH (canonical: "
        "C:/arcis/data/ai_research_desk.sqlite3 in .env at repo root). "
        "For Postgres deploys (Render), DATABASE_URL is auto-set by the "
        "platform. Stub fallback to halcyon-lab/ai_research_desk.sqlite3 "
        "was removed per CLAUDE.md #642 (Sprint 0 Wave 1d / DB-STUB-CFG)."
    )
DB_PATH: str | None = _DB_PATH_ENV  # None on Postgres-only deploys

_config_cache: dict | None = None

_logger = logging.getLogger(__name__)

# Email-consolidation (#115) deprecation-warning sentinels. Each warning
# fires ONCE per process to avoid log spam on every reload_config() call.
# Pattern mirrors src/email/notifier.py:21 (_yaml_password_warning_emitted).
_email_deprecation_warning_emitted = False
_bootcamp_email_mode_warning_emitted = False
_old_path_enabled_warning_emitted = False

# Email-consolidation (#115) weekly-tier-time DOW parser. Mon=0..Sun=6 to
# match datetime.weekday(). Used by parse_weekly_tier_time below + by
# Task 5's flush_tier scheduler.
_DOW_TO_WEEKDAY = {
    "MON": 0, "TUE": 1, "WED": 2, "THU": 3,
    "FRI": 4, "SAT": 5, "SUN": 6,
}

# Detects common placeholder patterns from settings.example.yaml (#132).
# Matches: "your-api-key", "YOUR_KEY_HERE", "placeholder", "example", ""
_PLACEHOLDER_RE = re.compile(r"^your[-_]|placeholder|example|YOUR_|^$", re.IGNORECASE)

_CRITICAL_KEYS = [
    ("alpaca", "api_key"),
    ("alpaca", "secret_key"),
    ("finnhub", "api_key"),
    ("fred", "api_key"),
    ("anthropic", "api_key"),
    ("telegram", "bot_token"),
]


def parse_weekly_tier_time(value: str) -> tuple[int, int, int]:
    """Parse the weekly tier-time string ``'<DOW> HH:MM'`` (DD-10, DA-NIT-20).

    DOW is one of Mon/Tue/Wed/Thu/Fri/Sat/Sun (case-insensitive). HH is
    00-23, MM is 00-59. Returns ``(weekday, hour, minute)`` where weekday
    follows :meth:`datetime.weekday` semantics (Mon=0..Sun=6).

    Raises:
        ValueError: with an operator-actionable remediation message when
            the input does not match ``'<DOW> HH:MM'`` exactly.
    """
    if not isinstance(value, str):
        raise ValueError(
            f"email.tier_times.weekly must be a string like 'Sun 18:00', got "
            f"{type(value).__name__}={value!r}. Format: '<DOW> HH:MM' where "
            f"DOW is one of Mon/Tue/Wed/Thu/Fri/Sat/Sun (case-insensitive)."
        )

    parts = value.strip().split()
    if len(parts) != 2:
        raise ValueError(
            f"email.tier_times.weekly={value!r} is malformed. Expected format "
            f"'<DOW> HH:MM' where DOW is one of Mon/Tue/Wed/Thu/Fri/Sat/Sun "
            f"(case-insensitive). Example: 'Sun 18:00'."
        )

    dow_str, hm_str = parts[0].upper(), parts[1]
    if dow_str not in _DOW_TO_WEEKDAY:
        raise ValueError(
            f"email.tier_times.weekly={value!r}: unknown day-of-week {parts[0]!r}. "
            f"Must be one of Mon/Tue/Wed/Thu/Fri/Sat/Sun (case-insensitive)."
        )

    hm_parts = hm_str.split(":")
    if len(hm_parts) != 2:
        raise ValueError(
            f"email.tier_times.weekly={value!r}: time must be 'HH:MM' "
            f"(24-hour), got {hm_str!r}."
        )
    try:
        hour = int(hm_parts[0])
        minute = int(hm_parts[1])
    except ValueError as e:
        raise ValueError(
            f"email.tier_times.weekly={value!r}: time must be 'HH:MM' with "
            f"integer hour (00-23) and minute (00-59), got {hm_str!r}."
        ) from e

    if not (0 <= hour <= 23) or not (0 <= minute <= 59):
        raise ValueError(
            f"email.tier_times.weekly={value!r}: time out of range. Hour "
            f"must be 00-23, minute must be 00-59, got hour={hour} minute={minute}."
        )

    return (_DOW_TO_WEEKDAY[dow_str], hour, minute)


def _apply_email_consolidation_defaults(config: dict) -> None:
    """In-place post-load normalization for the email-consolidation schema (#115).

    Per spec Section 4.5:
      - Map deprecated ``email.digest_times.{premarket,eod}`` → ``email.tier_times``
        when the new keys are absent. Emit ONE deprecation warning per process.
      - Default ``email.tier_times.{preopen,postclose,weekly}`` when absent.
      - Default ``email.tiers.<name>.{enabled, send_when_empty}`` per DD-33
        (preopen/postclose send_when_empty=False; weekly send_when_empty=True).
      - Default ``email.dual_write_hold_over.mode='shadow'`` (DD-20 revised).
      - Map legacy ``email.dual_write_hold_over.old_path_enabled`` →
        ``mode='shadow'`` (true) or ``mode='off'`` (false) when ``mode`` is
        absent. Emit deprecation warning.
      - Validate weekly tier_time via :func:`parse_weekly_tier_time` and
        re-raise ``ValueError`` so misconfiguration fails at load, not
        silently at flush time.
      - Collapse ``bootcamp.email_mode`` in {'full_stream','daily_summary'} →
        'digest' with deprecation warning (DD-11). 'silent'/'digest' are
        passed through unchanged.
    """
    global _email_deprecation_warning_emitted
    global _bootcamp_email_mode_warning_emitted
    global _old_path_enabled_warning_emitted

    email_cfg = config.setdefault("email", {})

    # ── tier_times: migrate from legacy digest_times when absent ─────
    existing_tier_times = email_cfg.get("tier_times") or {}
    legacy_digest_times = email_cfg.get("digest_times") or {}

    new_tier_times = dict(existing_tier_times)  # operator-set values win

    # Emit deprecation warning ONLY when legacy keys exist AND operator
    # has NOT migrated (i.e. new tier_times keys absent).
    legacy_present = bool(legacy_digest_times)
    new_present = bool(existing_tier_times)
    if legacy_present and not new_present:
        if not _email_deprecation_warning_emitted:
            _email_deprecation_warning_emitted = True
            _logger.warning(
                "email.digest_times.{premarket,midday,eod,evening} is "
                "deprecated; use email.tier_times.{preopen,postclose,weekly} "
                "instead. The legacy keys are being mapped (premarket→preopen, "
                "eod→postclose); midday/evening are folded into postclose. See "
                "spec #115 Section 4.5."
            )
        # Map the legacy values forward. New tier_times missing entirely,
        # so it is safe to write any mapped keys we have.
        if "premarket" in legacy_digest_times and "preopen" not in new_tier_times:
            new_tier_times["preopen"] = legacy_digest_times["premarket"]
        if "eod" in legacy_digest_times and "postclose" not in new_tier_times:
            new_tier_times["postclose"] = legacy_digest_times["eod"]

    # Apply DD-10 defaults for any tier_times still missing.
    new_tier_times.setdefault("preopen", "07:30")
    new_tier_times.setdefault("postclose", "17:00")
    new_tier_times.setdefault("weekly", "Sun 18:00")

    # Validate the weekly value at load time (DD-10/DA-NIT-20). This raises
    # ValueError on malformed input so the operator gets a remediation
    # message immediately rather than a silent failure at flush time.
    parse_weekly_tier_time(new_tier_times["weekly"])

    email_cfg["tier_times"] = new_tier_times

    # ── per-tier enabled + send_when_empty defaults (DD-07, DD-33) ───
    tiers = email_cfg.setdefault("tiers", {})
    for tier_name, default_send_when_empty in (
        ("preopen", False),
        ("postclose", False),
        ("weekly", True),
    ):
        tier_entry = tiers.setdefault(tier_name, {})
        tier_entry.setdefault("enabled", True)
        tier_entry.setdefault("send_when_empty", default_send_when_empty)

    # ── digest_truncation defaults (DD-05 revised, DD-19) ────────────
    truncation = email_cfg.setdefault("digest_truncation", {})
    truncation.setdefault("top_k_per_section", 10)
    truncation.setdefault("overflow_strategy", "attach_overflow_file")
    truncation.setdefault("overflow_attach_format", "plain")

    # ── holidays defaults (DD-21) ────────────────────────────────────
    holidays = email_cfg.setdefault("holidays", {})
    holidays.setdefault("skip_preopen_on_market_holidays", True)
    holidays.setdefault("skip_postclose_on_market_holidays", True)

    # ── dual_write_hold_over (DD-20 revised) ─────────────────────────
    holdover = email_cfg.setdefault("dual_write_hold_over", {})
    holdover.setdefault("enabled", True)
    holdover.setdefault("shadow_output_dir", "tmp/digest-shadow")

    explicit_mode = "mode" in holdover
    legacy_old_path = "old_path_enabled" in holdover
    if legacy_old_path and not explicit_mode:
        # Legacy alias: map old_path_enabled → mode. Emit deprecation warning.
        if not _old_path_enabled_warning_emitted:
            _old_path_enabled_warning_emitted = True
            _logger.warning(
                "email.dual_write_hold_over.old_path_enabled is deprecated; "
                "use email.dual_write_hold_over.mode={'shadow','time_aligned',"
                "'off'} directly. Mapping old_path_enabled=%r → mode=%r. See "
                "spec #115 DD-20 (revised).",
                holdover["old_path_enabled"],
                "shadow" if holdover["old_path_enabled"] else "off",
            )
        holdover["mode"] = "shadow" if holdover["old_path_enabled"] else "off"
    else:
        # Default when neither explicit mode nor legacy alias present.
        holdover.setdefault("mode", "shadow")

    holdover.setdefault("old_path_enabled", True)  # preserve legacy key shape

    # ── bootcamp.email_mode collapse (DD-11) ─────────────────────────
    bootcamp_cfg = config.get("bootcamp") or {}
    bc_mode = bootcamp_cfg.get("email_mode")
    if bc_mode in {"full_stream", "daily_summary"}:
        if not _bootcamp_email_mode_warning_emitted:
            _bootcamp_email_mode_warning_emitted = True
            _logger.warning(
                "bootcamp.email_mode=%r is deprecated; the value set has "
                "collapsed to {'silent','digest'}. Aliasing %r → 'digest'. See "
                "spec #115 DD-11.",
                bc_mode, bc_mode,
            )
        config["bootcamp"]["email_mode"] = "digest"


def validate_config(config: dict) -> list[str]:
    """Check critical config keys for placeholder values.

    Returns list of warning strings (key paths with placeholder values).
    Does not crash — returns empty list if config is missing sections.
    """
    warnings = []
    for section, key in _CRITICAL_KEYS:
        value = config.get(section, {}).get(key, None)
        if value is None:
            continue
        if not isinstance(value, str):
            continue
        if _PLACEHOLDER_RE.search(value) or value.strip() == "":
            warnings.append(f"{section}.{key} appears to be a placeholder")
    return warnings


def load_config() -> dict:
    """Load and return the application configuration dict (cached)."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    # __file__ is src/config/__init__.py, so parent.parent reaches project root.
    # ARCIS_CONFIG_DIR overrides for test fixtures (tmp_path injection).
    _override = os.environ.get("ARCIS_CONFIG_DIR")
    if _override:
        config_dir = Path(_override)
    else:
        config_dir = Path(__file__).resolve().parent.parent.parent / "config"
    local_path = config_dir / "settings.local.yaml"
    example_path = config_dir / "settings.example.yaml"

    if local_path.exists():
        config_path = local_path
    elif example_path.exists():
        print(
            "WARNING: config/settings.local.yaml not found, "
            "falling back to config/settings.example.yaml",
            file=sys.stderr,
        )
        config_path = example_path
    else:
        print("ERROR: No configuration file found.", file=sys.stderr)
        return {}

    with open(config_path, "r", encoding="utf-8") as f:
        _config_cache = yaml.safe_load(f) or {}

    # Email-consolidation (#115) — apply deprecation mapping + defaults.
    # Runs BEFORE validate_config so placeholder warnings reflect post-
    # normalization state.
    _apply_email_consolidation_defaults(_config_cache)

    # Validate config for placeholder keys
    config_warnings = validate_config(_config_cache)
    for w in config_warnings:
        _logger.warning("[CONFIG] %s", w)
    if config_path == example_path:
        _logger.warning("[CONFIG] Using example config — API keys are placeholders")

    return _config_cache


def get_config() -> dict:
    """Return the cached config (loads from disk if not cached yet)."""
    return load_config()


def reload_config() -> dict:
    """Force re-read of config from disk."""
    global _config_cache
    _config_cache = None
    return load_config()
