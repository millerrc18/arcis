"""Structural CI guards for the capability registry (Convention A-E).

This module implements hard (merge-blocking) structural guards. Each guard
derives its expected set from a live oracle (handler list, filename glob,
gate tuple, source-scan, package walk) rather than a static snapshot.

Task 2 scope: Convention B.
Task 3 scope: Convention A (watch-handler ACTIONs).
Task 4 scope: Convention C (governor-gate DECISIONs).
Task 10 scope: Convention D (registering-module-in-bootstrap meta-guard) and
Convention E (per-capability-package presence/coverage guard). These land last
per the sequencing contract in the design spec §8 (a meta/coverage guard must
land in the SAME batch as or after ALL its target registrations).
"""
from __future__ import annotations

import pathlib
import pkgutil
import re

import pytest

import src.data_collection as dc
from src.platform.capability_registry import (
    ensure_bootstrapped,
    list_actions,
    list_decisions,
    list_states,
    list_systems,
)
from src.platform.capability_registry.bootstrap import CAPABILITY_MODULES
from src.risk.governor import GOVERNOR_GATES
from src.scheduler.watch_handlers import ALL_HANDLERS

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    """Populate registries from production modules before any guard runs."""
    ensure_bootstrapped()
    yield


# ---------------------------------------------------------------------------
# Convention B — every src/data_collection/*_collector.py registers a SYSTEM
# ---------------------------------------------------------------------------

# EXEMPT contract: add a *_collector module stem here ONLY if it is a shared
# helper that hosts no real collector (none today).
# Each entry MUST carry a one-line reason.
EXEMPT: set[str] = set()


def test_every_collector_module_registers_a_system():
    """Every *_collector.py module stem has a corresponding data-collection SYSTEM.

    Oracle: pkgutil.iter_modules over src.data_collection — live code drives
    the expected set, so a new collector file that skips registration fails CI.

    Convention B EXEMPT contract: add a *_collector module stem to EXEMPT only
    if it is a shared helper that hosts no real collector. Each entry MUST carry
    a one-line reason. EXEMPT starts empty — no current exemptions.
    """
    expected = {
        n
        for _, n, _ in pkgutil.iter_modules(dc.__path__)
        if n.endswith("_collector") and n not in EXEMPT
    }
    registered = {s.name for s in list_systems() if s.category == "data-collection"}
    missing = expected - registered
    assert not missing, (
        f"Collector modules with no SYSTEM (name must == module stem): {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# Convention A — every ALL_HANDLERS handler is a registered ACTION
# ---------------------------------------------------------------------------

def _expected_action_name(h) -> str:
    n = h.__name__
    return n[len("maybe_"):] if n.startswith("maybe_") else n


def test_all_handlers_are_plain_maybe_functions():
    """Every handler in ALL_HANDLERS is a plain maybe_-prefixed function.

    DA-minor hardening: no partials/lambdas — each entry must be callable,
    have a __name__, and that name must start with 'maybe_'.
    """
    for h in ALL_HANDLERS:
        assert callable(h) and hasattr(h, "__name__"), (
            f"ALL_HANDLERS entry {h!r} is not a plain function with __name__"
        )
        assert h.__name__.startswith("maybe_"), (
            f"ALL_HANDLERS entry {h.__name__!r} does not start with 'maybe_'"
        )


def test_all_handlers_stripped_names_have_no_collisions():
    """maybe_-strip produces no duplicate ACTION names across ALL_HANDLERS.

    DA-minor hardening: 16 handlers must produce 16 distinct stripped names.
    """
    stripped = [_expected_action_name(h) for h in ALL_HANDLERS]
    unique = set(stripped)
    assert len(unique) == len(ALL_HANDLERS), (
        f"maybe_-strip produced colliding ACTION names: "
        f"{len(ALL_HANDLERS)} handlers -> {len(unique)} names"
    )


def test_every_watch_handler_is_a_registered_action():
    """Every fn in ALL_HANDLERS maps to a registered ACTION (maybe_-stripped name).

    Oracle: ALL_HANDLERS list — live code drives the expected set, so a new
    handler that skips registration fails CI.
    """
    expected = {_expected_action_name(h) for h in ALL_HANDLERS}
    registered_names = {a.name for a in list_actions()}
    missing = expected - registered_names
    assert not missing, (
        f"Watch handlers without a registered ACTION: {sorted(missing)}"
    )


def test_action_count_increased_by_16():
    """Exactly 16 new scheduler ACTIONs are registered (one per ALL_HANDLERS handler)."""
    scheduler_actions = [a for a in list_actions() if a.category == "scheduler"]
    assert len(scheduler_actions) == 16, (
        f"Expected 16 scheduler category ACTIONs; found {len(scheduler_actions)}: "
        f"{sorted(a.name for a in scheduler_actions)}"
    )


# ---------------------------------------------------------------------------
# Convention C — every GOVERNOR_GATES entry is a registered DECISION gate_<g>
# (DA-4: definition enumeration from the GOVERNOR_GATES tuple, NO check_trade
# dry-run — check_trade short-circuits at governor.py:613/680 so no fixture
# emits all 11 gate names. The tuple is the oracle.)
# ---------------------------------------------------------------------------

def test_every_governor_gate_is_a_registered_decision():
    """Every GOVERNOR_GATES entry maps to a registered DECISION named gate_<g>.

    Oracle: src.risk.governor.GOVERNOR_GATES (the gate-definition tuple) — live
    code drives the expected set, so a new gate that skips its register_decision
    fails CI. This is robust definition-enumeration, not a fragile dry-run.
    """
    expected = {f"gate_{g}" for g in GOVERNOR_GATES}
    registered_names = {d.name for d in list_decisions()}
    missing = expected - registered_names
    assert not missing, (
        f"Governor gates missing register_decision: {sorted(missing)}"
    )


def test_risk_governor_category_decisions_count():
    """Exactly 12 risk-governor DECISIONs: 11 gates + decision_drawdown_adjusted_risk."""
    risk_decisions = [d for d in list_decisions() if d.category == "risk-governor"]
    assert len(risk_decisions) == 12, (
        f"Expected 12 risk-governor DECISIONs (11 gates + drawdown); "
        f"found {len(risk_decisions)}: {sorted(d.name for d in risk_decisions)}"
    )


def test_risk_governor_system_registered():
    """The risk_governor SYSTEM is registered exactly once."""
    governors = [s for s in list_systems() if s.name == "risk_governor"]
    assert len(governors) == 1, (
        f"Expected exactly one risk_governor SYSTEM; found {len(governors)}"
    )


# ---------------------------------------------------------------------------
# T5 — Execution / exits family (keep 3)
# ---------------------------------------------------------------------------

def test_t5_submit_shadow_trade_action_registered():
    """submit_shadow_trade ACTION is registered (T5 keep-set)."""
    names = {a.name for a in list_actions()}
    assert "submit_shadow_trade" in names, (
        "submit_shadow_trade ACTION missing from registry"
    )


def test_t5_position_exit_manager_system_registered():
    """position_exit_manager SYSTEM is registered (T5 keep-set)."""
    names = {s.name for s in list_systems()}
    assert "position_exit_manager" in names, (
        "position_exit_manager SYSTEM missing from registry"
    )


def test_t5_trade_reconciler_system_registered():
    """trade_reconciler SYSTEM is registered — distinct from reconcile_trades (T5)."""
    names = {s.name for s in list_systems()}
    assert "trade_reconciler" in names, (
        "trade_reconciler SYSTEM missing from registry"
    )
    assert "reconcile_trades" in names, (
        "pre-existing reconcile_trades SYSTEM must still be present"
    )


def test_t5_health_fns_degrade_not_raise():
    """position_exit_manager and trade_reconciler health fns return valid status dicts."""
    from src.shadow_trading.capability_registration import (
        _position_exit_manager_health,
        _trade_reconciler_health,
    )
    for fn in (_position_exit_manager_health, _trade_reconciler_health):
        result = fn()
        assert isinstance(result, dict), f"{fn.__name__} must return dict"
        assert result.get("status") in {"ok", "degraded", "down"}, (
            f"{fn.__name__} returned invalid status: {result}"
        )


def test_t5_submit_shadow_trade_schema_valid():
    """submit_shadow_trade input_schema is a valid Draft-7 object schema."""
    from jsonschema import Draft7Validator
    actions = {a.name: a for a in list_actions()}
    action = actions["submit_shadow_trade"]
    Draft7Validator.check_schema(action.input_schema)
    assert action.input_schema.get("type") == "object"


# ---------------------------------------------------------------------------
# T6 — Scan / LLM / council family (keep 3)
# ---------------------------------------------------------------------------

def test_t6_llm_scorer_system_registered():
    """llm_scorer SYSTEM is registered (T6 keep-set)."""
    names = {s.name for s in list_systems()}
    assert "llm_scorer" in names, "llm_scorer SYSTEM missing from registry"


def test_t6_council_engine_system_registered():
    """council_engine SYSTEM is registered (T6 keep-set)."""
    names = {s.name for s in list_systems()}
    assert "council_engine" in names, "council_engine SYSTEM missing from registry"


def test_t6_build_decision_packet_action_registered():
    """build_decision_packet ACTION is registered (T6 keep-set)."""
    names = {a.name for a in list_actions()}
    assert "build_decision_packet" in names, (
        "build_decision_packet ACTION missing from registry"
    )


def test_t6_health_fns_degrade_not_raise():
    """llm_scorer and council_engine health fns return valid status dicts (bare env)."""
    from src.llm.capability_registration import _llm_scorer_health
    from src.council.capability_registration import _council_engine_health
    for fn in (_llm_scorer_health, _council_engine_health):
        result = fn()
        assert isinstance(result, dict), f"{fn.__name__} must return dict"
        assert result.get("status") in {"ok", "degraded", "down"}, (
            f"{fn.__name__} returned invalid status: {result}"
        )


def test_t6_build_decision_packet_schema_valid():
    """build_decision_packet input_schema is a valid Draft-7 object schema."""
    from jsonschema import Draft7Validator
    actions = {a.name: a for a in list_actions()}
    action = actions["build_decision_packet"]
    Draft7Validator.check_schema(action.input_schema)
    assert action.input_schema.get("type") == "object"


# ---------------------------------------------------------------------------
# T7 — Training pipeline family (keep 3)
# ---------------------------------------------------------------------------

def test_t7_run_finetune_action_registered():
    """run_finetune ACTION is registered (T7 keep-set)."""
    names = {a.name for a in list_actions()}
    assert "run_finetune" in names, "run_finetune ACTION missing from registry"


def test_t7_model_promotion_gate_decision_registered():
    """model_promotion_gate DECISION is registered (T7 keep-set)."""
    names = {d.name for d in list_decisions()}
    assert "model_promotion_gate" in names, (
        "model_promotion_gate DECISION missing from registry"
    )


def test_t7_training_quality_filter_decision_registered():
    """training_quality_filter DECISION is registered (T7 keep-set)."""
    names = {d.name for d in list_decisions()}
    assert "training_quality_filter" in names, (
        "training_quality_filter DECISION missing from registry"
    )


def test_t7_run_finetune_schema_valid():
    """run_finetune input_schema is a valid Draft-7 object schema."""
    from jsonschema import Draft7Validator
    actions = {a.name: a for a in list_actions()}
    action = actions["run_finetune"]
    Draft7Validator.check_schema(action.input_schema)
    assert action.input_schema.get("type") == "object"


def test_t7_no_collision_with_existing_training_entries():
    """T7 registrations do not collide with existing training_corpus / training_data_audit."""
    action_names = {a.name for a in list_actions()}
    state_names = {s.name for s in list_states()}
    assert "training_corpus" in state_names, "pre-existing training_corpus STATE must remain"
    assert "training_data_audit" in action_names, (
        "pre-existing training_data_audit ACTION must remain"
    )


# ---------------------------------------------------------------------------
# T8 — Evaluation / audit family (keep 3)
# ---------------------------------------------------------------------------

def test_t8_system_auditor_system_registered():
    """system_auditor SYSTEM is registered (T8 keep-set)."""
    names = {s.name for s in list_systems()}
    assert "system_auditor" in names, "system_auditor SYSTEM missing from registry"


def test_t8_model_monitor_system_registered():
    """model_monitor SYSTEM is registered (T8 keep-set)."""
    names = {s.name for s in list_systems()}
    assert "model_monitor" in names, "model_monitor SYSTEM missing from registry"


def test_t8_run_backtest_action_registered():
    """run_backtest ACTION is registered — distinct from strategy_backtest (T8 keep-set)."""
    action_names = {a.name for a in list_actions()}
    assert "run_backtest" in action_names, "run_backtest ACTION missing from registry"
    assert "strategy_backtest" in action_names, (
        "pre-existing strategy_backtest ACTION must still be present"
    )


def test_t8_health_fns_degrade_not_raise():
    """system_auditor and model_monitor health fns return valid status dicts (bare env)."""
    from src.evaluation.capability_registration import (
        _system_auditor_health,
        _model_monitor_health,
    )
    for fn in (_system_auditor_health, _model_monitor_health):
        result = fn()
        assert isinstance(result, dict), f"{fn.__name__} must return dict"
        assert result.get("status") in {"ok", "degraded", "down"}, (
            f"{fn.__name__} returned invalid status: {result}"
        )


def test_t8_run_backtest_schema_valid():
    """run_backtest input_schema is a valid Draft-7 object schema."""
    from jsonschema import Draft7Validator
    actions = {a.name: a for a in list_actions()}
    action = actions["run_backtest"]
    Draft7Validator.check_schema(action.input_schema)
    assert action.input_schema.get("type") == "object"


# ---------------------------------------------------------------------------
# T9 — Notifications / attribution family (keep 2)
# ---------------------------------------------------------------------------

def test_t9_telegram_notifier_system_registered():
    """telegram_notifier SYSTEM is registered (T9 keep-set)."""
    names = {s.name for s in list_systems()}
    assert "telegram_notifier" in names, "telegram_notifier SYSTEM missing from registry"


def test_t9_spy_benchmark_state_registered():
    """spy_benchmark_state STATE is registered (T9 keep-set)."""
    names = {s.name for s in list_states()}
    assert "spy_benchmark_state" in names, "spy_benchmark_state STATE missing from registry"


def test_t9_telegram_notifier_health_degrades_not_raises():
    """telegram_notifier health fn returns valid status dict (bare env, no token)."""
    from src.notifications.capability_registration import _telegram_notifier_health
    result = _telegram_notifier_health()
    assert isinstance(result, dict), "_telegram_notifier_health must return dict"
    assert result.get("status") in {"ok", "degraded", "down"}, (
        f"_telegram_notifier_health returned invalid status: {result}"
    )


def test_t9_spy_benchmark_state_query_returns_value_key():
    """spy_benchmark_state query fn returns a dict with a 'value' key (bare env)."""
    from src.notifications.capability_registration import _spy_benchmark_query
    result = _spy_benchmark_query()
    assert isinstance(result, dict), "_spy_benchmark_query must return dict"
    assert "value" in result, f"_spy_benchmark_query missing 'value' key: {result}"


def test_t9_no_collision_with_attribution_resolver():
    """T9 registrations do not collide with existing attribution_resolver SYSTEM."""
    names = {s.name for s in list_systems()}
    assert "attribution_resolver" in names, (
        "pre-existing attribution_resolver SYSTEM must still be present"
    )


# ---------------------------------------------------------------------------
# Convention D (meta-guard) — every module containing a registration is in
# bootstrap.CAPABILITY_MODULES.
#
# DA-minor: the en-bloc family hosts (data_collection.capability_registration,
# risk.gate_decisions) and the existing decisions.py use the FUNCTIONAL call
# form — register_system(...)(fn), register_decision(...) — NOT the @-decorator.
# The detection regex MUST catch BOTH forms or a functionally-registering host
# could be dropped from CAPABILITY_MODULES and silently fail to load.
#
# The (?<!def ) lookbehind excludes the `def register_x(` definitions in the
# registry package itself (registry.py / __init__.py / schemas.py), which DEFINE
# the API rather than call it. decisions.py and audit_registration.py are real
# hosts inside that package and ARE required to be listed.
# ---------------------------------------------------------------------------

_REGISTER_PAT = re.compile(
    r"@register_(?:action|state|system|decision)\b"
    r"|(?<!def )register_(?:action|state|system|decision)\("
)
_SELF_PKG = "src.platform.capability_registry"
# Modules inside the registry package that are real hosts (not API definitions).
_SELF_PKG_HOSTS = {
    f"{_SELF_PKG}.decisions",
    f"{_SELF_PKG}.audit_registration",
}
# Comment-only lines produce false positives (e.g. a docstring/comment that
# names @register_action prose). Strip whole-line and trailing comments before
# scanning so D detects real registration code, not prose about it.
_COMMENT = re.compile(r"#.*$", re.M)


def _module_dotted_name(path: pathlib.Path) -> str:
    """Dotted import name for a src/ file; a package __init__ maps to the package.

    Importing a package name runs its __init__.py, so a registration in
    src/diagnostics/__init__.py fires when bootstrap lists "src.diagnostics" —
    the two are the same import target and must compare equal.
    """
    mod = ".".join(path.relative_to(_SRC.parent).with_suffix("").parts)
    if mod.endswith(".__init__"):
        mod = mod[: -len(".__init__")]
    return mod


def _registers_in_code(text: str) -> bool:
    """True if the source contains a real register_* call/decorator (not in a comment)."""
    return bool(_REGISTER_PAT.search(_COMMENT.sub("", text)))


def test_every_registering_module_is_in_bootstrap():
    """Every src/ module that registers a capability is in CAPABILITY_MODULES.

    Oracle: a source-scan of src/ for the register_* pattern (decorator OR
    functional call). A module that registers a capability but is absent from
    bootstrap would silently fail to load (its decorators never fire), so this
    guards against the forgotten-bootstrap-entry drift.

    The registry package itself DEFINES register_* (excluded via the SELF_PKG
    filter + the (?<!def ) lookbehind); its real hosts (decisions.py,
    audit_registration.py) are kept in scope and must be listed.
    """
    listed = set(CAPABILITY_MODULES)
    offenders: list[str] = []
    for p in _SRC.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        if not _registers_in_code(text):
            continue
        mod = _module_dotted_name(p)
        if mod.startswith(_SELF_PKG) and mod not in _SELF_PKG_HOSTS:
            continue
        if mod not in listed:
            offenders.append(mod)
    assert not offenders, (
        "Modules register capabilities but are absent from "
        f"CAPABILITY_MODULES: {sorted(offenders)}. Add each to "
        "bootstrap.CAPABILITY_MODULES so its decorators fire at bootstrap."
    )


def test_convention_d_pattern_catches_functional_form():
    """D self-test (DA-minor): the regex detects the functional call form.

    The en-bloc loop hosts register via register_system(...)(fn) and
    register_decision(...). If the pattern only matched the @-decorator form,
    those hosts could drift out of CAPABILITY_MODULES undetected. This proves
    both forms are caught and the `def register_x(` definitions are excluded.
    """
    assert _REGISTER_PAT.search("register_system(name='x')(fn)")
    assert _REGISTER_PAT.search("    register_decision(name='y')")
    assert _REGISTER_PAT.search("register_action(name='a')(fn)")
    assert _REGISTER_PAT.search("register_state(name='s')(fn)")
    assert _REGISTER_PAT.search("@register_action(name='z')")
    assert _REGISTER_PAT.search("@register_system\n")
    assert not _REGISTER_PAT.search("def register_system(**meta):")
    assert not _REGISTER_PAT.search("def register_decision(**meta):")


# ---------------------------------------------------------------------------
# Convention E (presence/coverage guard) — every business-logic module under an
# enumerated capability package registers >= 1 capability (directly, or via a
# sibling capability_registration.py thin-host) OR is explicitly EXEMPT.
#
# DA-2: A/B/C structurally cover only the 47-entry firm core (handlers /
# collectors / gates). The heterogeneous + existing entries had NO structural
# anti-drift guard, so a NEW undecorated subsystem under execution / training /
# eval / council / notifications would silently drift — the exact failure this
# work exists to prevent. E derives an expected set from code structure: a new
# business-logic module under a capability package that registers nothing and
# is not EXEMPT -> CI red.
#
# E is intentionally MODULE-granular. The honest residual (a new public FUNCTION
# inside an already-registered module) is NOT caught by any guard and is a
# review-time call (see design spec §5.0 / §10). We do NOT claim "CI prevents
# all drift"; we claim "CI prevents a new capability-package module from
# registering nothing without an explicit, reasoned exemption."
#
# EXEMPT_MODULES is the on-the-record "modules we deliberately chose not to
# surface this pass" list. It is checked BEFORE the sibling-host shortcut, so
# the deferred-backlog entries are load-bearing (removing one re-arms E for that
# module) rather than cosmetic. Promoting a deferred item later = remove its
# EXEMPT entry + register it (E then requires it). Every entry carries a reason.
# ---------------------------------------------------------------------------

CAPABILITY_PACKAGES = (
    "src/shadow_trading",
    "src/llm",
    "src/council",
    "src/training",
    "src/evaluation",
    "src/notifications",
    "src/ranking",
    "src/analytics",
)

EXEMPT_MODULES: dict[str, str] = {
    # --- Deferred backlog (design spec §3-defer) — recorded in
    #     docs/audits/2026-05-21-capability-registry/deferred_backlog.md.
    #     Each is a second-tier engine/decision deferred to a future pass.
    # Execution / exits (T5)
    "src.shadow_trading.exit_reason": "deferred: exit_reason_classifier DECISION (backlog)",
    "src.shadow_trading.bracket_monitor": "deferred: bracket_monitor SYSTEM — covered operationally by position_exit_manager (backlog)",
    # Scan / LLM / council (T6)
    "src.council.aggregation": "deferred: council_aggregation DECISION (backlog)",
    "src.llm.watchlist_writer": "deferred: build_watchlist ACTION (backlog)",
    "src.llm.postmortem_writer": "deferred: trade_postmortem ACTION (backlog)",
    # Training (T7)
    "src.training.dpo_pipeline": "deferred: run_dpo ACTION (backlog)",
    "src.training.data_collector": "deferred: build_training_corpus support (backlog)",
    # Evaluation (T8)
    "src.evaluation.system_validator": "deferred: system_validator SYSTEM (backlog)",
    "src.evaluation.walkforward": "deferred: walkforward_validation SYSTEM (backlog)",
    "src.evaluation.scorecard": "deferred: build_scorecard ACTION (backlog)",
    "src.evaluation.build_score": "deferred: build_scorecard support (backlog)",
    "src.evaluation.change_detector": "deferred: change_detector SYSTEM (backlog)",
    # Notifications (T9)
    "src.notifications.telegram_commands": "deferred: telegram_command_handler ACTION (backlog)",
    "src.notifications.policy": "deferred: notification_policy DECISION (backlog)",
    "src.notifications.platform_events": "deferred: platform_event_bus SYSTEM (backlog)",
    # --- Infrastructure / sub-package helpers with no capability_registration
    #     host of their own (not deferred capabilities; pure support code).
    "src.training.audit.core": "training-audit pass orchestrator — support code, no business capability",
    "src.training.audit.pass_a_citation": "training-audit citation pass — support code",
    "src.training.audit.pass_b_format": "training-audit format pass — support code",
    "src.training.audit.pass_c_leakage": "training-audit leakage pass — support code",
    "src.training.audit.report": "training-audit report renderer — support code",
    "src.training.audit.taxonomy": "training-audit taxonomy constants/helpers — support code",
    "src.ranking.ranker": "candidate ranker — deferred candidate_ranking; no ranking capability_registration host this pass (backlog)",
    "src.analytics.canonical_sharpe": "analytics math helper — support code, surfaced via spy_benchmark_state",
    "src.analytics.instrumentation": "analytics instrumentation plumbing — support code",
    "src.analytics.instrumentation_filter": "analytics instrumentation filter — support code",
    "src.analytics.kpis_compute": "analytics KPI computation — support code, no capability_registration host this pass",
    "src.analytics.spy_benchmark": "analytics SPY benchmark loader — surfaced via spy_benchmark_state STATE (notifications host)",
}

# Stems that are pure helpers/leaves and never host business logic — skipped
# before the EXEMPT check so the manifest stays focused on real subsystems.
_HELPER_HINT = re.compile(
    r"^_|_helpers?$|^errors?$|^constants?$|^types?$|^_status_sql$|^_capability_health$"
)
# A module has business logic if it defines at least one public def/class.
_BUSINESS_LOGIC = re.compile(r"^(?:async def |def |class )[A-Za-z]", re.M)


def test_every_capability_package_module_surfaces_or_is_exempt():
    """Every business-logic module under a capability package surfaces a
    capability or is explicitly EXEMPT (Convention E — DA-2).

    For each module under CAPABILITY_PACKAGES (excluding __init__.py, the
    package's own capability_registration.py, and pure-helper stems):
      - if it is in EXEMPT_MODULES, it is on-the-record-deliberately-skipped: OK
      - else it must register directly (register_* in its source) OR be covered
        by a sibling capability_registration.py thin-host in CAPABILITY_MODULES
      - otherwise it is an offender: a new subsystem may have drifted in.

    EXEMPT_MODULES is checked BEFORE the sibling-host shortcut so each deferred
    entry is load-bearing. The failure message is a precise, actionable list.
    """
    ensure_bootstrapped()
    listed_hosts = set(CAPABILITY_MODULES)
    offenders: list[str] = []
    for pkg in CAPABILITY_PACKAGES:
        pkg_dir = _SRC.parent / pkg
        if not pkg_dir.exists():
            continue
        for p in pkg_dir.rglob("*.py"):
            if p.name in {"__init__.py", "capability_registration.py"}:
                continue
            if _HELPER_HINT.search(p.stem):
                continue
            mod = ".".join(p.relative_to(_SRC.parent).with_suffix("").parts)
            if mod in EXEMPT_MODULES:
                continue
            text = p.read_text(encoding="utf-8")
            if not _BUSINESS_LOGIC.search(text):
                continue
            registers_here = bool(_REGISTER_PAT.search(text))
            sibling_host = f"{mod.rsplit('.', 1)[0]}.capability_registration"
            if not (registers_here or sibling_host in listed_hosts):
                offenders.append(mod)
    assert not offenders, (
        "Modules under a capability package register no capability and are not "
        f"EXEMPT — a new subsystem may have drifted in: {sorted(offenders)}. "
        "Either register a capability for it, or add it to EXEMPT_MODULES with "
        "a one-line reason (and to deferred_backlog.md if it is a deferral)."
    )


def test_convention_e_exempt_modules_all_carry_reasons():
    """Every EXEMPT_MODULES entry carries a non-empty reason string.

    The manifest doubles as the on-the-record 'deliberately not surfaced' list;
    a bare exemption with no rationale would defeat that purpose.
    """
    for mod, reason in EXEMPT_MODULES.items():
        assert isinstance(reason, str) and reason.strip(), (
            f"EXEMPT_MODULES[{mod!r}] must carry a non-empty reason"
        )


def test_convention_e_exempt_modules_exist_on_disk():
    """Every EXEMPT_MODULES key maps to a real source file.

    Prevents the manifest from rotting: a renamed/deleted module whose EXEMPT
    entry lingers would silently mask a real future offender.
    """
    missing = []
    for mod in EXEMPT_MODULES:
        rel = pathlib.Path(*mod.split(".")).with_suffix(".py")
        if not (_SRC.parent / rel).exists():
            missing.append(mod)
    assert not missing, (
        f"EXEMPT_MODULES keys with no source file (stale entries): {sorted(missing)}"
    )
