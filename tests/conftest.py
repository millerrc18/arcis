"""Shared test fixtures and helpers.

Provides init_test_db() to create all schema tables in a temp database,
replacing the per-module CREATE TABLE statements removed during the
schema registry migration (PR #189).

Also provides mock Alpaca modules via sys.modules injection so that
deferred imports inside alpaca_adapter.py resolve to mocks without
requiring the alpaca-py SDK at test time.

Docker PG fixture (T9):
pg_docker_url — session-scoped fixture that provisions an ephemeral
Postgres via docker-compose.test.yml (port 5434). If docker is
unavailable it falls back to the hardcoded CI URL
(postgresql://test:test@localhost/halcyon) so CI's pg-tests.yml
continues to work unchanged.  Three test files (tests/api/test_status.py,
tests/test_cloud_app.py, tests/test_shadow_desk_filter.py) consume this
fixture via their autouse set_env / set_db_env fixtures rather than
hardcoding DATABASE_URL themselves.
"""

import os


# ---------------------------------------------------------------------------
# P0 GUARD — must run BEFORE any test module is imported
# ---------------------------------------------------------------------------
#
# Incident 2026-05-14 08:37 ET: all 76 tables in the operator's local Docker
# halcyon PG database were dropped.  Root cause: 24 test files use the broken
# fallback pattern
#
#     TEST_PG_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
#
# When pytest is run in the operator's shell, src/config/__init__.py loads
# .env at import time (transitive `import src.*`).  .env injects
# DATABASE_URL=postgresql://halcyon_app:...@localhost:5433/halcyon (the
# production PG).  Because TEST_DATABASE_URL is not set in the operator's
# .env, the fallback resolves to the production PG URL, and those fixtures
# execute DROP TABLE ... CASCADE against production.
#
# This hook fires at pytest_configure time — the EARLIEST possible hook,
# before any test module is collected or imported.
#
# To proceed legitimately when DATABASE_URL points at production PG, either:
#   1. Set TEST_DATABASE_URL to a safe test PG (e.g. halcyon-pg-test on 5434)
#   2. Set ARCIS_ALLOW_PROD_PG_IN_TESTS=1  (escape hatch for intentional use)
#   3. Unset DATABASE_URL before running pytest


_PROD_SIGNATURES = ("localhost:5433", "127.0.0.1:5433", "halcyon_app:")


def _is_prod_pg_url(url: str) -> bool:
    """Return True when `url` matches any production-PG signature.

    Used by both the P0 guard at pytest_configure (catches operator env
    misconfiguration) and at fixture-entry time (catches autouse fixtures
    that mutate env mid-session).
    """
    return bool(url) and any(sig in url for sig in _PROD_SIGNATURES)


# Env snapshot captured pre-collection (end of pytest_configure) and restored in
# pytest_collection_finish. Guards against import-time os.environ scrubs poisoning
# the whole session at collection: src/simulation/lifecycle/bootstrap.py:90 runs a
# module-level _scrub_environment() that rewrites os.environ (TEST_DATABASE_URL ->
# sim 127.0.0.1:5434, ARCIS_PG_CUTOVER_ENABLED=1, pops ARCIS_DB_PATH). pytest
# collection imports that module (full_gate <- test_entrypoints), so without this
# ~130 engine-aware / [postgres] tests connect to a 5434 PG the standard pg-tests
# CI job does not provision and fail with connection-refused.
_PRECOLLECT_ENV: dict = {}

# PR-E2 T43 green-gate sentinel (DD-42 §46): (nodeid, reason) for every skip
# that ACTUALLY FIRED this run. Checked at pytest_sessionfinish against the
# DD-42 allowlist; any fired skip without an allowlisted reason fails the run.
_GREEN_GATE_FIRED_SKIPS: list = []


def pytest_configure(config):
    """P0 GUARD: refuse pytest if DATABASE_URL or TEST_DATABASE_URL points at prod PG.

    Runs at the earliest pytest hook, before any test module is imported.
    Calls pytest.exit(returncode=2) with a loud explanatory message if the
    operator's environment would cause test fixtures to DROP TABLE against
    the production Postgres database.

    v0.36.14: extended to also check TEST_DATABASE_URL. P0 incident
    2026-05-17 21:28 UTC (#159) wiped ~80 prod tables when a coding-team
    developer agent collected `tests/notifications/test_platform_events.py`
    whose autouse fixture constructed a TEST_DATABASE_URL pointing at port
    5433 (prod). The pg_wrapper fixture trusted that env var and DROPped
    every sync-eligible table on teardown. The prior P0 guard only
    inspected DATABASE_URL and missed this path entirely.
    """
    import pytest as _pytest

    # #96 (2026-05-22 prod-wipe RCCA): close the timing hole. src/config loads
    # .env LAZILY on the first `import src.*`, which can happen AFTER this hook —
    # so a cwd/.env-provided prod DATABASE_URL (e.g. a worktree's copied .env) used
    # to slip past this guard and only materialize mid-run, routing DROP/DELETE at
    # production. Load .env HERE, before reading the env, so the guard sees it at the
    # earliest hook. override=False so a real shell TEST_DATABASE_URL still wins.
    try:
        from dotenv import load_dotenv

        load_dotenv(override=False)
    except Exception:
        pass

    db_url = os.environ.get("DATABASE_URL", "")
    test_db_url = os.environ.get("TEST_DATABASE_URL", "")
    allow_override = os.environ.get("ARCIS_ALLOW_PROD_PG_IN_TESTS", "").lower() in (
        "1",
        "true",
        "yes",
    )

    db_url_is_prod = _is_prod_pg_url(db_url)
    test_db_url_is_prod = _is_prod_pg_url(test_db_url)

    if test_db_url_is_prod and not allow_override:
        _pytest.exit(
            "\n"
            + "=" * 70 + "\n"
            "  P0 GUARD: REFUSING PYTEST — TEST_DATABASE_URL POINTS AT PRODUCTION PG\n"
            + "=" * 70 + "\n"
            "\n"
            "  DANGER: TEST_DATABASE_URL in your environment resolves to the\n"
            "  operator's production Postgres database (detected signatures:\n"
            "  localhost:5433, 127.0.0.1:5433, or halcyon_app: in the URL).\n"
            "\n"
            "  Several fixtures in tests/conftest.py (pg_wrapper, pg_isolated_conn)\n"
            "  read TEST_DATABASE_URL and run DROP TABLE IF EXISTS ... CASCADE on\n"
            "  teardown. With this URL pointing at production, every sync-eligible\n"
            "  table would be dropped — this happened on 2026-05-17 (P0 incident\n"
            "  #159, ~80 prod tables wiped).\n"
            "\n"
            "  HOW TO FIX:\n"
            "    set TEST_DATABASE_URL=postgresql://test:test@127.0.0.1:5434/halcyon\n"
            "  Or unset and let pg_wrapper skip:\n"
            "    set TEST_DATABASE_URL=\n"
            "\n"
            "  Current TEST_DATABASE_URL (redacted after @): "
            + (test_db_url.split("@")[0] + "@..." if "@" in test_db_url else test_db_url)
            + "\n"
            + "=" * 70 + "\n",
            returncode=2,
        )

    if db_url_is_prod and not test_db_url and not allow_override:
        _pytest.exit(
            "\n"
            + "=" * 70 + "\n"
            "  P0 GUARD: REFUSING PYTEST — DATABASE_URL POINTS AT PRODUCTION PG\n"
            + "=" * 70 + "\n"
            "\n"
            "  DANGER: DATABASE_URL in your environment resolves to the operator's\n"
            "  production Postgres database (detected signatures: localhost:5433,\n"
            "  127.0.0.1:5433, or halcyon_app: in the URL).  24 test files use the\n"
            "  broken fallback pattern:\n"
            "\n"
            "      TEST_PG_URL = os.environ.get('TEST_DATABASE_URL') or \\\n"
            "                    os.environ.get('DATABASE_URL', '')\n"
            "\n"
            "  If pytest were allowed to proceed, fixtures in those files would\n"
            "  execute  DROP TABLE IF EXISTS ... CASCADE  against production,\n"
            "  wiping all data.  This happened on 2026-05-14 (P0 incident #158).\n"
            "\n"
            "  HOW TO FIX — pick ONE of the following:\n"
            "\n"
            "  1. Point tests at the TEST Postgres (recommended):\n"
            "         set TEST_DATABASE_URL=postgresql://test:test@127.0.0.1:5434/halcyon\n"
            "     The operator's halcyon-pg-test container runs on port 5434.\n"
            "\n"
            "  2. Unset DATABASE_URL before running pytest:\n"
            "         set DATABASE_URL=\n"
            "         python -m pytest ...\n"
            "\n"
            "  3. Explicitly opt in (ONLY if you truly know what you are doing):\n"
            "         set ARCIS_ALLOW_PROD_PG_IN_TESTS=1\n"
            "         python -m pytest ...\n"
            "\n"
            "  Current DATABASE_URL (redacted after @): "
            + (db_url.split("@")[0] + "@..." if "@" in db_url else db_url)
            + "\n"
            + "=" * 70 + "\n",
            returncode=2,
        )

    # Snapshot the intended test env BEFORE collection imports run. Collection
    # imports modules whose top-level code may scrub os.environ (the lifecycle
    # bootstrap — see _PRECOLLECT_ENV note above); pytest_collection_finish
    # restores this so tests run against the CI/operator DB env, not the scrub.
    _PRECOLLECT_ENV.clear()
    _PRECOLLECT_ENV.update(os.environ)


def pytest_collection_finish(session):
    """Restore the pre-collection env, undoing any import-time os.environ scrub
    that ran while pytest imported test modules during collection. Without this
    the lifecycle bootstrap's module-level scrub (bootstrap.py:90) leaks
    TEST_DATABASE_URL=...:5434 / ARCIS_PG_CUTOVER_ENABLED / popped ARCIS_DB_PATH
    into every test in the session. Module-level code runs once per import, so a
    single post-collection restore is sufficient (no re-pollution)."""
    if not _PRECOLLECT_ENV:
        return
    for key in list(os.environ.keys()):
        if key not in _PRECOLLECT_ENV:
            del os.environ[key]
    for key, value in _PRECOLLECT_ENV.items():
        if os.environ.get(key) != value:
            os.environ[key] = value


def pytest_runtest_logreport(report):
    """PR-E2 T43 (DD-42 §46): record skips that ACTUALLY FIRED this run.

    Excludes xfails (an xfailed test reports as skipped but carries `wasxfail`)
    — those are legitimate expected-failures, governed separately by
    xfail_strict=true (an xpass becomes a real failure). For a genuine skip,
    `report.longrepr` is the 3-tuple (path, lineno, "Skipped: <reason>").
    """
    if report.skipped and not getattr(report, "wasxfail", None):
        longrepr = report.longrepr
        if isinstance(longrepr, tuple) and len(longrepr) >= 3:
            reason = str(longrepr[2])
        else:
            reason = str(longrepr)
        _GREEN_GATE_FIRED_SKIPS.append((report.nodeid, reason))


def pytest_sessionfinish(session, exitstatus):
    """PR-E2 T43 (DD-42 §46): fail the run if any fired skip is unjustified.

    The green-gate policy: every skip must carry a reason in a DD-42
    allowlisted category (platform / optional-dep / engine-aware /
    tracked-upstream-bug(#N) / integration(authoritative-coverage:<job>)).
    Conditional skips that did not fire in this environment are not checked.

    Only overrides exitstatus when it is currently 0 (all-green) so genuine
    test failures (already non-zero) are never masked.
    """
    if not _GREEN_GATE_FIRED_SKIPS:
        return
    try:
        from tests.test_suite_integrity import is_justified_skip
    except Exception:
        # Matcher unavailable (e.g. collection-only / odd invocation) — do not
        # crash the run; the sentinel's own self-tests cover the matcher.
        return
    offenders = [
        (nid, reason)
        for nid, reason in _GREEN_GATE_FIRED_SKIPS
        if not is_justified_skip(reason)
    ]
    if offenders:
        # Fail FIRST so a reporting hiccup can never mask the gate result. Only
        # override a clean exit (0) — genuine test failures stay non-zero.
        if session.exitstatus == 0:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

        # ASCII-safe: skip reasons may contain non-ASCII (>=, em-dash). On Windows
        # the captured stdout is cp1252 and a raw print() of those chars raises
        # UnicodeEncodeError, which would crash pytest_sessionfinish and swallow
        # the report. backslashreplace keeps the text legible without crashing.
        def _ascii(s: str) -> str:
            return str(s).encode("ascii", "backslashreplace").decode("ascii")

        line = "=" * 70
        report = [
            "",
            line,
            "[GREEN-GATE] DD-42 sec.46 - skips fired without an allowlisted reason:",
            "  (allowlist: platform | optional-dep | engine-aware |",
            "   tracked-upstream-bug(#N) | integration(authoritative-coverage:<job>))",
        ]
        for nid, reason in offenders:
            report.append(f"  - {_ascii(nid)}\n      reason: {_ascii(reason)}")
        report.append(line)
        print("\n".join(report))


import datetime
import shutil
import sqlite3
import subprocess
import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

# ---------------------------------------------------------------------------
# Mock yfinance if not installed (prevents 22+ import failures in CI)
# ---------------------------------------------------------------------------
if "yfinance" not in sys.modules:
    _yf_mock = types.ModuleType("yfinance")
    _yf_mock.download = MagicMock(return_value=None)
    _yf_mock.Ticker = MagicMock
    sys.modules["yfinance"] = _yf_mock

from src.schema.registry import TABLES
from src.schema.sqlite import generate_create_sql


def init_test_db(db_path: str, tables: list[str] | None = None) -> None:
    """Create schema tables in a test database.

    Args:
        db_path: Path to the SQLite database file.
        tables: Optional list of table names to create. If None, creates all.
    """
    conn = sqlite3.connect(db_path)
    try:
        if tables is None:
            for tdef in TABLES.values():
                conn.executescript(generate_create_sql(tdef))
        else:
            for name in tables:
                if name in TABLES:
                    conn.executescript(generate_create_sql(TABLES[name]))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Mock Alpaca SDK modules for deferred-import compatibility
# ---------------------------------------------------------------------------

class _MockEnum:
    """Enum-like object whose attributes return named values."""
    def __init__(self, name, value):
        self._name = name
        self._value = value
        self.value = value
    def __repr__(self):
        return f"{self._name}"


class _MockEnumClass:
    """Factory that produces _MockEnum instances for attribute access."""
    def __init__(self, name):
        self._name = name
    def __getattr__(self, item):
        return _MockEnum(f"{self._name}.{item}", item.lower())


class _MockOrderRequest:
    """Mock for MarketOrderRequest / LimitOrderRequest.

    Stores all constructor kwargs as attributes so tests can inspect
    request.symbol, request.qty, request.time_in_force.value, etc.
    """
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def _build_mock_alpaca_modules():
    """Create a tree of mock alpaca modules for sys.modules injection."""
    alpaca = types.ModuleType("alpaca")
    trading = types.ModuleType("alpaca.trading")
    trading_client = types.ModuleType("alpaca.trading.client")
    trading_requests = types.ModuleType("alpaca.trading.requests")
    trading_enums = types.ModuleType("alpaca.trading.enums")
    data = types.ModuleType("alpaca.data")
    data_historical = types.ModuleType("alpaca.data.historical")
    data_requests = types.ModuleType("alpaca.data.requests")
    common = types.ModuleType("alpaca.common")
    common_exceptions = types.ModuleType("alpaca.common.exceptions")

    # Wire up parent-child relationships
    alpaca.trading = trading
    alpaca.data = data
    alpaca.common = common
    trading.client = trading_client
    trading.requests = trading_requests
    trading.enums = trading_enums
    data.historical = data_historical
    data.requests = data_requests
    common.exceptions = common_exceptions

    # Populate classes
    trading_client.TradingClient = MagicMock(name="TradingClient")
    trading_requests.MarketOrderRequest = _MockOrderRequest
    trading_requests.LimitOrderRequest = _MockOrderRequest
    trading_requests.StopOrderRequest = _MockOrderRequest
    trading_requests.GetOrdersRequest = _MockOrderRequest  # Fix #356
    trading_enums.OrderSide = _MockEnumClass("OrderSide")
    trading_enums.TimeInForce = _MockEnumClass("TimeInForce")
    trading_enums.OrderClass = _MockEnumClass("OrderClass")
    trading_enums.QueryOrderStatus = _MockEnumClass("QueryOrderStatus")  # Fix #356
    data_historical.StockHistoricalDataClient = MagicMock(name="StockHistoricalDataClient")
    data_requests.StockLatestTradeRequest = MagicMock(name="StockLatestTradeRequest")
    common_exceptions.APIError = type("APIError", (Exception,), {"status_code": None, "code": None, "message": None})

    return {
        "alpaca": alpaca,
        "alpaca.trading": trading,
        "alpaca.trading.client": trading_client,
        "alpaca.trading.requests": trading_requests,
        "alpaca.trading.enums": trading_enums,
        "alpaca.data": data,
        "alpaca.data.historical": data_historical,
        "alpaca.data.requests": data_requests,
        "alpaca.common": common,
        "alpaca.common.exceptions": common_exceptions,
    }


@pytest.fixture(autouse=True)
def _mock_alpaca_sdk(monkeypatch):
    """Inject mock alpaca modules into sys.modules.

    This ensures deferred imports like ``from alpaca.trading.enums import
    OrderSide`` inside alpaca_adapter.py resolve to lightweight mocks,
    satisfying CLAUDE.md's "mock all external APIs in tests" rule.
    """
    mods = _build_mock_alpaca_modules()
    for mod_name, mod_obj in mods.items():
        monkeypatch.setitem(sys.modules, mod_name, mod_obj)


@pytest.fixture(autouse=True)
def _reset_enricher_rate_limit_state():
    """Clear the enricher's module-global per-API rate-limit timestamps per test.

    src/data_enrichment/enricher.py keeps `_last_request_time: dict[str, float]`
    at module scope. A freezegun test frozen to a FUTURE date that triggers any
    enrichment call records a future timestamp there. After the freeze lifts,
    a later test's _rate_limit() computes `interval - (now - future_last)` =
    `interval + (future - now)` and calls time.sleep() for that huge delta —
    hanging until the per-test timeout hard-kills the whole pytest process
    (observed: tests/simulation/lifecycle/test_scenario.py wedged the full-suite
    run at the enricher rate limiter, though it passes in isolation).

    Clearing the dict before AND after each test removes any leaked timestamp so
    no test can inherit a poisoned future `last`. Bounded real intervals (<=1s)
    mean a clean dict never sleeps meaningfully.
    """
    try:
        from src.data_enrichment import enricher as _enr
        _enr._last_request_time.clear()
    except Exception:
        _enr = None
    yield
    if _enr is not None:
        try:
            _enr._last_request_time.clear()
        except Exception:
            pass


# Test-Determinism #128 T6 — restore reimported src.training / lifecycle-bootstrap
# modules so a stale module object can't defeat a later test's @patch.
#
# Several tests pop-and-reimport (or importlib.reload) modules in the
# src.training package and src.simulation.lifecycle.bootstrap, e.g.
#   tests/simulation/lifecycle/test_trainer_stub.py:89-96
#       sys.modules.pop("src.training.trainer"/"training_stop"/"training_control")
#       then importlib.import_module("src.training.trainer")
#   tests/simulation/lifecycle/test_bootstrap.py:60-62
#       importlib.reload(src.simulation.lifecycle.bootstrap)
# A raw sys.modules.pop()/reload() is NOT undone by monkeypatch, so after such a
# test sys.modules["src.training.trainer"] is a DIFFERENT module object than the
# one tests/test_trainer.py bound at collection time via
#   from src.training.trainer import should_train
# When test_trainer.py then runs, @patch("src.training.trainer.load_config", ...)
# patches the NEW module's namespace, but the already-bound should_train reads
# load_config / get_training_split_viability from its OLD __globals__ — so the
# patch is silently VACUOUS and the real (config-enabled, holdout-empty) path
# runs. Symptom (verify-by-mutation, fixed-order: test_trainer_stub THEN
# test_trainer):
#   test_should_train_true_when_threshold_met -> trigger False (real viability ran)
#   test_should_train_false_when_disabled     -> reason "holdout empty" not "disabled"
# tests/test_self_blinding.py exhibits the same family via src.training.data_collector.
# All three PASS in isolation, FAIL only after a reimporting test runs first
# (the #1192 Class-C "process-global leaked by an earlier test" root cause).
#
# Fix at the SOURCE of the leak's blast radius: snapshot the canonical module
# objects once (the clean import already present in sys.modules at session start)
# and, after each test, restore any src.training.* / bootstrap entry whose
# identity changed. This is the conftest autouse snapshot/restore pattern the
# plan prescribes (precedent: _reset_enricher_rate_limit_state above). The
# reimporting tests still see their fresh module DURING their own run (we restore
# only AFTER yield), so their behavior is unchanged.
@pytest.fixture(scope="session")
def _training_module_snapshot():
    """Canonical (clean) module objects for the reimport-prone training modules."""
    names = [
        "src.training.trainer",
        "src.training.training_stop",
        "src.training.training_control",
        "src.training.data_collector",
        "src.simulation.lifecycle.bootstrap",
    ]
    # Import each so the snapshot holds the canonical object even if no earlier
    # test imported it yet; failures (optional deps) are tolerated.
    snapshot = {}
    import importlib as _il
    for name in names:
        try:
            snapshot[name] = _il.import_module(name)
        except Exception:
            pass
    return snapshot


@pytest.fixture(autouse=True)
def _restore_training_modules(_training_module_snapshot):
    """Restore canonical src.training / lifecycle-bootstrap modules after each test.

    Neutralizes a leaked stale module object (left by a pop+reimport or reload in
    an earlier test) that would otherwise make a later test's @patch vacuous
    (#128 T6 / #1192 Class-C; test_trainer + test_self_blinding).
    """
    yield
    for name, canonical in _training_module_snapshot.items():
        if sys.modules.get(name) is not canonical:
            sys.modules[name] = canonical


# Test-Determinism #128 T6 — clear the /api/cto-report response memo per test.
#
# src/api/cloud_routes/analytics.py keeps a module-level `_cto_cache: dict`
# (analytics.py:38) memoizing the /api/cto-report response by `days` for
# _CTO_CACHE_TTL_SECONDS (300s). The FIRST cto-report hit in a process fills
# `_cto_cache[days]`; within the 5-minute TTL every later hit for the same
# `days` returns the cached payload and never re-queries the (mock) runtime.
# tests/test_dashboard_reconciliation.py::test_all_endpoints_emit_meta hits
# /api/cto-report with the default fixture (closed_count=5), filling the memo;
# then test_closed_count_reconciles seeds closed_count=7 and hits the same
# endpoint — but gets the stale 5-trade payload back, so
# cto._meta.trade_summary.n=5 != shadow._meta.n=7. Passes in isolation (memo
# empty), fails in full-suite ordering once any earlier test populated it.
# This is the #1192 Class-C "process-global leaked by an earlier test" root
# cause for test_closed_count_reconciles (confirmed: a full fixed-order run of
# tests/ surfaces exactly this one failure; clearing the memo per test fixes
# it). The memo has no production reset hook (it is TTL-only), so we clear the
# dict directly — same precedent as _reset_enricher_rate_limit_state above,
# which clears src.data_enrichment.enricher._last_request_time per test.
@pytest.fixture(autouse=True)
def _reset_cto_report_cache():
    """Clear src.api.cloud_routes.analytics._cto_cache before AND after each test.

    Prevents a stale /api/cto-report response (memoized for 300s by `days`)
    from an earlier test leaking into a later test that seeds a different
    closed-trade count (#128 T6 / #1192 Class-C order-dependent isolation leak;
    test_dashboard_reconciliation::test_closed_count_reconciles).
    """
    try:
        from src.api.cloud_routes import analytics as _an
        _an._cto_cache.clear()
    except Exception:
        _an = None
    yield
    if _an is not None:
        try:
            _an._cto_cache.clear()
        except Exception:
            pass


# Test-Determinism #128 T1 — deterministic policy clock.
#
# The notification policy gate (src/notifications/policy.py) routes events to
# digest/mute during quiet hours. safe_send (src/notifications/telegram.py)
# reads the time via telegram._now_et_for_safe_send() and passes it to
# should_dispatch; should_dispatch itself falls back to policy._now_et_provider()
# when now_et is None. Both time sources read real wall-clock ET in production,
# which made any test that drove safe_send (e.g. the governor/auditor disabled
# alerts) silently route to the digest queue at night — failing because the
# SQLite test fixtures don't provision notifications_digest_queue. This is the
# Class-A "night-flake" root cause in docs/audits/2026-05-30-test-determinism.
#
# _pin_policy_clock_daytime (autouse) pins BOTH time sources to a fixed DAYTIME
# instant (14:00 ET, outside the default 22:00-06:00 quiet window) so alert
# tests are time-deterministic. Tests that DO exercise the quiet-hours->digest
# branch opt into freeze_quiet_hours, which re-pins to 03:00 ET.

_POLICY_CLOCK_DAYTIME = datetime.datetime(2026, 6, 1, 14, 0, tzinfo=ZoneInfo("America/New_York"))
_POLICY_CLOCK_QUIET = datetime.datetime(2026, 6, 1, 3, 0, tzinfo=ZoneInfo("America/New_York"))


def _pin_policy_clock(monkeypatch, when):
    """Pin all notification time sources to `when`. Reverts via monkeypatch.

    Covers three seams:
      - policy._now_et_provider          (quiet-hours routing in should_dispatch)
      - telegram._now_et_for_safe_send   (the now_et safe_send passes to policy)
      - telegram_commands._now_et_provider (#128 T4: day-of-week / time-of-day
        branches in check_action_reminders + the _cmd_* handlers). The default
        daytime instant (_POLICY_CLOCK_DAYTIME) is a WEEKDAY (Mon 2026-06-01),
        so the Sunday-conditional reminder branches deterministically do NOT
        fire — killing the Class-A "Sunday flake".
    """
    import src.notifications.policy as _policy
    import src.notifications.telegram as _telegram
    import src.notifications.telegram_commands as _telegram_commands

    monkeypatch.setattr(_policy, "_now_et_provider", lambda: when)
    monkeypatch.setattr(_telegram, "_now_et_for_safe_send", lambda: when)
    monkeypatch.setattr(_telegram_commands, "_now_et_provider", lambda: when)


@pytest.fixture(autouse=True)
def _pin_policy_clock_daytime(monkeypatch):
    """Autouse: pin the notification clocks to a fixed DAYTIME WEEKDAY instant.

    Makes notification/alert tests independent of wall-clock time-of-day (#128
    T1) AND day-of-week (#128 T4 — extends the pin to
    telegram_commands._now_et_provider so the Sunday-gated action reminders are
    deterministic; _POLICY_CLOCK_DAYTIME is Mon 2026-06-01). Tests needing
    quiet-hours behavior use the freeze_quiet_hours fixture, whose own
    _pin_policy_clock call overrides this one at function scope. Tests that pass
    an explicit datetime to should_dispatch / resolve_pending_outcomes, or that
    pin telegram_commands._now_et_provider themselves, are unaffected.
    """
    _pin_policy_clock(monkeypatch, _POLICY_CLOCK_DAYTIME)


@pytest.fixture
def freeze_quiet_hours(monkeypatch):
    """Opt-in: pin the notification policy clock to quiet-hours (03:00 ET).

    Use in tests that exercise the quiet-hours -> digest routing branch so the
    digest path is reachable deterministically (#128 T1). Overrides the autouse
    daytime pin for the duration of the test.
    """
    _pin_policy_clock(monkeypatch, _POLICY_CLOCK_QUIET)
    return _POLICY_CLOCK_QUIET


@pytest.fixture(autouse=True)
def _isolate_local_api_token_env(monkeypatch):
    """Hermetic test env: clear ARCIS_LOCAL_API_TOKEN.

    Operator .env files in local dev set ARCIS_LOCAL_API_TOKEN to exercise
    verify_local_token (opt-in via #576). Without this fixture, TestClient
    requests against gated endpoints (/api/notes, /api/scan, /api/training,
    /api/review, /api/commands, /api/settings, etc.) get 401 because pytest
    inherits the operator's env. Tests that need the env var (e.g.,
    test_phase_d_auth_and_safety, test_helper_coverage_backfill) still
    work — their monkeypatch.setenv overrides this delenv at function scope.
    """
    monkeypatch.delenv("ARCIS_LOCAL_API_TOKEN", raising=False)


@pytest.fixture
def schema_db(tmp_path):
    """Temp database with ALL schema tables created.

    Use this when a test needs database access but you don't want
    to specify individual tables. Slightly slower than init_test_db
    with a specific table list, but guaranteed to have everything.
    """
    path = str(tmp_path / "test.db")
    init_test_db(path)
    return path


@pytest.fixture(scope="function")
def postgres_session():
    """Postgres session fixture for parametrized reconciliation tests.

    Yields a connection-like object whose .execute() delegates to psycopg2.
    Scoped to function (not session) to isolate state per test, per
    reviewer item #12.

    SAFETY: reads ONLY `TEST_DATABASE_URL`, never `DATABASE_URL`. The
    operator's `.env` puts production Render `DATABASE_URL` on the path
    (load_dotenv walks up from worktrees), and CLAUDE.md "Tests must NEVER
    write to the prod DB" forbids using it for tests. Operator must
    explicitly opt-in by setting `TEST_DATABASE_URL` to a separate
    test/staging Postgres URL.

    SKIP GUARD: parametrize decorator in test_dashboard_reconciliation.py
    uses pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), ...)
    at collection time so the skip fires before the fixture body runs.
    When TEST_DATABASE_URL is absent the postgres parametrize variant is
    SKIPPED (not FAILED) — total test count is stable across environments.
    """
    import psycopg2
    import psycopg2.extras

    test_database_url = os.environ.get("TEST_DATABASE_URL")
    if not test_database_url:
        pytest.skip("TEST_DATABASE_URL not set; postgres fixture cannot run")
    conn = psycopg2.connect(test_database_url, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


# ---------------------------------------------------------------------------
# Sprint 5 §J5/§J6 Phase 0 T0.9 — pg_wrapper + parametrized_conn
# ---------------------------------------------------------------------------
#
# Two fixtures so engine-aware helpers can be tested against BOTH SQLite and
# Postgres without per-test boilerplate. `pg_wrapper` returns a
# `PostgresConnectionWrapper` (the same shape `connect_db()` returns when
# `DATABASE_URL` points at Postgres) so call sites exercise the wrapper's
# cursor / execute / `?`->`%s` rewrite paths end-to-end. `parametrized_conn`
# wraps both engines under a single fixture that's auto-parametrized over
# `engine=['sqlite', 'postgres']`, with the postgres variant skipping cleanly
# when `TEST_DATABASE_URL` is unset.
#
# Schema bootstrap on the PG side uses `src.schema.postgres.generate_create_sql`
# to create the same registry-defined tables that exist on the SQLite side.
# The fixture tracks the created table names and drops them on teardown so
# the test/staging Postgres database returns to a clean slate after each test.
# Tables that already exist are left untouched (CREATE TABLE IF NOT EXISTS),
# but only the table names this fixture itself bootstrapped are dropped on
# cleanup — so a long-running test database with pre-existing tables is safe.
#
# SAFETY: same as postgres_session — reads ONLY `TEST_DATABASE_URL`, never
# `DATABASE_URL`. Operator must explicitly opt-in.


@pytest.fixture(scope="function")
def pg_wrapper():
    """PostgresConnectionWrapper fixture for engine-parametrized tests.

    Yields a `PostgresConnectionWrapper` backed by a psycopg2 RealDictCursor
    connection to `TEST_DATABASE_URL`. Bootstraps all registry tables via
    `src.schema.postgres.generate_create_sql` and drops the tables this
    fixture itself created on teardown.

    SAFETY: reads ONLY `TEST_DATABASE_URL`, never `DATABASE_URL`. When
    `TEST_DATABASE_URL` is unset, the fixture calls `pytest.skip()` so the
    test is reported SKIPPED (not FAILED) and the total test count stays
    stable across environments.

    SKIP GUARD: the skip happens INSIDE the fixture body so parametrized
    callers (`parametrized_conn`) can request `pg_wrapper` lazily via
    `request.getfixturevalue("pg_wrapper")` and have the sqlite variant
    proceed unconditionally while the postgres variant skips cleanly.
    """
    import psycopg2
    import psycopg2.extras

    from src.schema.postgres import generate_create_sql
    from src.schema.registry import TABLES
    from src.utils.db import PostgresConnectionWrapper

    test_database_url = os.environ.get("TEST_DATABASE_URL")
    if not test_database_url:
        pytest.skip("TEST_DATABASE_URL not set; pg_wrapper fixture cannot run")

    # v0.36.14 second-line defense: refuse prod URLs even if pytest_configure
    # let them through (e.g., an autouse fixture mutated env after configure
    # ran). This is the case that wiped ~80 prod tables on 2026-05-17 (#159).
    if _is_prod_pg_url(test_database_url):
        pytest.fail(
            "pg_wrapper refused to connect: TEST_DATABASE_URL matches prod "
            "signatures (localhost:5433 / 127.0.0.1:5433 / halcyon_app:). "
            "An earlier fixture or test module likely mutated TEST_DATABASE_URL "
            "to point at production. See tests/conftest.py pytest_configure "
            "guard for the operator-facing fix-it message."
        )

    raw_conn = psycopg2.connect(
        test_database_url, cursor_factory=psycopg2.extras.RealDictCursor
    )
    raw_conn.autocommit = True
    created_tables: list[str] = []
    cur = raw_conn.cursor()
    try:
        # Phase 1: CREATE TABLE IF NOT EXISTS for every sync-eligible table.
        # generate_create_sql emits CREATE TABLE IF NOT EXISTS + CREATE INDEX
        # IF NOT EXISTS so the call is idempotent on a pre-populated DB.
        for tdef in TABLES.values():
            if not tdef.sync_to_postgres:
                continue
            cur.execute(generate_create_sql(tdef))
            created_tables.append(tdef.name)
    except Exception:
        cur.close()
        raw_conn.close()
        raise

    raw_conn.autocommit = False
    wrapper = PostgresConnectionWrapper(raw_conn)
    try:
        yield wrapper
    finally:
        try:
            raw_conn.rollback()
        except Exception:
            pass
        # Teardown: drop the tables this fixture created. autocommit=True so
        # each DROP commits independently — partial cleanup is preferable to
        # leaving the test DB in a half-rolled-back state.
        try:
            raw_conn.autocommit = True
            cleanup_cur = raw_conn.cursor()
            for name in reversed(created_tables):
                try:
                    cleanup_cur.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
                except Exception:
                    pass
            cleanup_cur.close()
        finally:
            raw_conn.close()


@pytest.fixture(params=["sqlite", "postgres"])
def parametrized_conn(request, tmp_path):
    """Engine-parametrized DB fixture exposing a `.execute()` callable.

    Parametrized over `engine=['sqlite', 'postgres']`. The 'sqlite' variant
    yields a `sqlite3.Connection` against a fresh tmp database populated by
    `init_test_db()`. The 'postgres' variant yields the `pg_wrapper`
    `PostgresConnectionWrapper` (which itself skips when `TEST_DATABASE_URL`
    is unset).

    Callers get a uniform `.execute(sql, params=None)` surface across both
    engines — the wrapper's `_rewrite_question_to_pct` translates SQLite-
    style `?` placeholders to psycopg2-style `%s` transparently, so cross-
    engine tests can write a single `?`-placeholder query.

    Lazy fixture request: 'postgres' variant requests `pg_wrapper` via
    `request.getfixturevalue` so the sqlite variant runs unconditionally
    and the postgres variant skips cleanly when `TEST_DATABASE_URL` is
    absent.
    """
    engine = request.param
    if engine == "sqlite":
        db_path = str(tmp_path / "test.db")
        init_test_db(db_path)
        conn = sqlite3.connect(db_path)
        # row_factory=sqlite3.Row so named-column access (`row["col"]`) is
        # available across both engines, matching psycopg2 RealDictCursor.
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    elif engine == "postgres":
        wrapper = request.getfixturevalue("pg_wrapper")
        yield wrapper
    else:
        raise ValueError(f"unknown engine param: {engine!r}")


# ---------------------------------------------------------------------------
# T9 — Local PG provisioning via docker-compose
# ---------------------------------------------------------------------------
#
# session-scoped: container is started ONCE per pytest session and torn down
# at the end. All tests that consume pg_docker_url (directly or via the
# autouse set_env / set_db_env fixtures in the 3 cross-engine test files)
# share the same container.
#
# Fallback: if docker is not available (e.g. bare-metal CI, developer machine
# without Docker Desktop), the fixture falls back to the hardcoded CI URL
# postgresql://test:test@localhost/halcyon.  CI's pg-tests.yml creates that
# role and runs the suite unchanged — no modification to the workflow needed.
#
# DATABASE_URL and TEST_DATABASE_URL are both set at session scope so:
#   1. connect_db() sees DATABASE_URL when the gate is off (Phase 0) and the
#      fixture just needs the URL in the env for cloud_app module-reload paths.
#   2. postgres_session / pg_wrapper fixtures read TEST_DATABASE_URL.

_COMPOSE_FILE = str(
    Path(__file__).parent.parent / "docker-compose.test.yml"
)
_TEST_PG_URL = "postgresql://test:test@127.0.0.1:5434/halcyon"
_CI_FALLBACK_URL = "postgresql://test:test@localhost/halcyon"


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _compose_up() -> bool:
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", _COMPOSE_FILE, "up", "-d", "--wait"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _compose_down() -> None:
    try:
        subprocess.run(
            ["docker", "compose", "-f", _COMPOSE_FILE, "down", "-v"],
            capture_output=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass


def _wait_for_pg(url: str, *, retries: int = 20, delay: float = 1.0) -> bool:
    try:
        import psycopg2
    except ImportError:
        return False
    for _ in range(retries):
        try:
            conn = psycopg2.connect(url, connect_timeout=3)
            conn.close()
            return True
        except Exception:
            time.sleep(delay)
    return False


@pytest.fixture(scope="session")
def pg_docker_url():
    """Session-scoped fixture — provision ephemeral PG for cross-engine tests.

    Start the docker-compose.test.yml container (postgres:16-alpine on
    port 5434).  Set DATABASE_URL and TEST_DATABASE_URL for the session.
    Tear down the container at session end.

    If docker is unavailable (CI bare-metal, no Docker Desktop) the fixture
    falls back to the hardcoded CI URL postgresql://test:test@localhost/halcyon
    so CI's pg-tests.yml continues to work unchanged.
    """
    # Respect an already-provisioned Postgres on EITHER env var before spinning
    # our own docker container. CI's pg-tests job sets a stable TEST_DATABASE_URL
    # (its 5432 service) but NOT DATABASE_URL (it uses ARCIS_DB_PATH); the old
    # check only inspected DATABASE_URL, so this fixture overwrote the stable
    # TEST_DATABASE_URL with a flaky docker-compose PG on 5434 — producing ~130
    # "connection refused 127.0.0.1:5434" failures across the engine-aware /
    # [postgres]-parametrized tests. Prefer the provided URL.
    already_set = os.environ.get("DATABASE_URL", "") or os.environ.get("TEST_DATABASE_URL", "")
    if already_set.startswith("postgres"):
        yield already_set
        return

    url = _CI_FALLBACK_URL
    started_container = False

    if _docker_available():
        if _compose_up():
            if _wait_for_pg(_TEST_PG_URL):
                url = _TEST_PG_URL
                started_container = True

    old_db_url = os.environ.get("DATABASE_URL")
    old_test_db_url = os.environ.get("TEST_DATABASE_URL")

    os.environ["DATABASE_URL"] = url
    os.environ["TEST_DATABASE_URL"] = url

    try:
        yield url
    finally:
        if old_db_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_db_url

        if old_test_db_url is None:
            os.environ.pop("TEST_DATABASE_URL", None)
        else:
            os.environ["TEST_DATABASE_URL"] = old_test_db_url

        if started_container:
            _compose_down()


# ---------------------------------------------------------------------------
# T13 D4 — Telegram isolation (#101)
# ---------------------------------------------------------------------------
#
# Three hooks that ensure pytest cannot accidentally fire real Telegram API calls:
#
# 1. _telegram_null_router_session (session-scoped, autouse):
#    - Sets ARCIS_NOTIFICATION_SOURCE to "pytest:<worktree-basename>" so every
#      digest-queue row written during tests carries an identifiable source_tag.
#    - Replaces src.notifications.telegram._send_single with a _null_router stub
#      that returns True without making HTTP calls. Session-scoped so the patch
#      is in place for the entire pytest run; individual tests that need to inspect
#      _send_single behaviour patch it further at function scope via their own
#      context managers, which override the session-level stub during that test only.
#
# 2. _telegram_token_clear_per_test (function-scoped, autouse):
#    - Clears ARCIS_TELEGRAM_TOKEN per-test via monkeypatch so operator .env
#      values cannot leak into tests (hermetic pattern from PR #729).
#    - monkeypatch is function-scoped so the clear is automatically reverted after
#      each test — tests that need the token set can still use monkeypatch.setenv
#      at function scope to override.


def _make_null_router(original_fn):
    """Return a _null_router stub that:
    - Returns True (no HTTP call) when requests.post is NOT mocked — the normal
      case where tests do not explicitly probe the HTTP transport layer.
    - Calls through to the original _send_single when requests.post IS mocked —
      this preserves existing tests that explicitly verify the HTTP call is made
      with correct parameters (e.g. test_telegram_send_path, test_telegram_chunked_send).
      Those tests mock requests.post precisely to intercept and inspect it, which
      signals they are intentionally testing the HTTP transport path.
    """
    import unittest.mock as _mock
    import requests as _requests

    def _null_router(cfg, text, parse_mode):
        if isinstance(_requests.post, _mock.MagicMock):
            return original_fn(cfg, text, parse_mode)
        return True

    _null_router.__name__ = "_null_router"
    return _null_router


@pytest.fixture(scope="session", autouse=True)
def _telegram_null_router_session():
    """Session-scoped: set source_tag env var + patch _send_single to null router.

    Covers the full pytest session so no test can accidentally fire real Telegram
    messages. Patches _send_single (the lowest HTTP-making function) so that:
    - notify_* functions get the null router and never reach requests.post
    - Tests that specifically test the send_telegram → _send_single → requests.post
      pipeline mock requests.post explicitly, which signals they are testing HTTP
      transport. The null router detects this and calls through to the original.

    Tests that explicitly need to inspect _send_single itself can restore it at
    function scope via unittest.mock.patch context managers.
    """
    import src.notifications.telegram as _tg

    worktree_name = Path.cwd().name
    old_source = os.environ.get("ARCIS_NOTIFICATION_SOURCE")
    os.environ["ARCIS_NOTIFICATION_SOURCE"] = f"pytest:{worktree_name}"

    original_send_single = _tg._send_single
    _tg._send_single = _make_null_router(original_send_single)

    try:
        yield
    finally:
        _tg._send_single = original_send_single
        if old_source is None:
            os.environ.pop("ARCIS_NOTIFICATION_SOURCE", None)
        else:
            os.environ["ARCIS_NOTIFICATION_SOURCE"] = old_source


@pytest.fixture(autouse=True)
def _telegram_token_clear_per_test(monkeypatch):
    """Function-scoped: clear ARCIS_TELEGRAM_TOKEN before each test.

    Prevents operator .env ARCIS_TELEGRAM_TOKEN from leaking into tests.
    Uses monkeypatch so the clear is reverted after each test — tests that
    explicitly set the token via monkeypatch.setenv still work correctly.
    """
    monkeypatch.delenv("ARCIS_TELEGRAM_TOKEN", raising=False)
