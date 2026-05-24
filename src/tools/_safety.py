"""Safety primitives for the tool suite — SafeOp, SafetyWindowGuard, ProdGuard.

Per #104 (v0.36.57): the three primitives that every mutating tool must
opt into. Composed as nested decorators on tool entry points.

Usage pattern (composed):

    @safe_op(name="nssm_restart", mutates=True)
    @safety_window("no_restart_overnight")
    @prod_guard(dsn_param="dsn")
    def restart_service(service: str, dsn: str, *, confirm: bool = False, emergency: bool = False):
        ...

Outer to inner: safe_op handles dry-run dispatch first (cheap short-circuit
on unconfirmed mutations), then safety_window checks the time-of-day,
then prod_guard checks the DSN signature, then the real function runs.

Audit: each decorator writes its OWN event to data/logs/tool-execution.log:
  - safe_op writes "dry_run" / "success" / "error"
  - safety_window writes "safety_window_block" when blocked
  - prod_guard writes "prod_guard_block" when blocked

Errors that come from safety_window/prod_guard are NOT double-logged by
safe_op — they're recognized as SafetyError subclasses and re-raised
without rewriting an "error" event.

Called by: tool entry points under src/tools/<subpackage>/
Calls: src.tools._config (window defs, prod DSN signatures), src.tools._execution_log
Owns tables: none
Config keys: safety_windows.* + pg.prod_dsn_signatures (all in config/arcis_config.yaml)
Tests: tests/tools/test_safety.py
"""

from __future__ import annotations

import functools
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Union
from zoneinfo import ZoneInfo

from src.tools._config import load_arcis_config
from src.tools._execution_log import sanitize_params, write_event


_ET = ZoneInfo("America/New_York")


# ═══════════════════════════════════════════════════════════════════
# Errors
# ═══════════════════════════════════════════════════════════════════


class SafetyError(RuntimeError):
    """Base class for safety-primitive refusals — NOT a generic runtime error.

    Subclasses (SafetyWindowError, ProdGuardError) are raised by their
    respective guards and recognized by safe_op so the "error" log event
    is not double-written (each guard logs its own specific block event).
    """


class SafetyWindowError(SafetyError):
    """Raised by SafetyWindowGuard when a mutating op is attempted in a blocked window."""


class ProdGuardError(SafetyError):
    """Raised by ProdGuard when a prod-signature DSN is passed without env+confirm."""


# ═══════════════════════════════════════════════════════════════════
# Part 1 — SafeOp + DryRunResult
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class DryRunResult:
    """What WOULD happen if a mutating tool ran with `confirm=True`.

    Frozen dataclass. Fields:
      tool_name: identifier from the @safe_op decorator
      would_do:  human-readable description (either from describe() lambda
                 or the default template)
      params:    sanitized kwargs the tool would receive
      timestamp: ISO 8601 with ET offset, for audit correlation
    """

    tool_name: str
    would_do: str
    params: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def __repr__(self) -> str:
        # Multi-line operator-readable. Indented param block. Distinct visual
        # marker (DRY RUN) so terminal output is unambiguous.
        param_lines = "\n".join(f"      {k}: {v!r}" for k, v in self.params.items())
        return (
            f"DryRunResult(\n"
            f"  tool_name: {self.tool_name}\n"
            f"  would_do:  {self.would_do}\n"
            f"  params:\n{param_lines}\n"
            f"  timestamp: {self.timestamp}\n"
            f")"
        )

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-serializable dict — for parent-agent consumption."""
        return asdict(self)


def _default_describe(tool_name: str, kwargs: dict[str, Any]) -> str:
    """Fallback dry-run description when no describe lambda is provided."""
    return f"Would invoke {tool_name} with params={sanitize_params(kwargs)}"


def _build_dry_run(name, kwargs, describe, log_target):
    """Dry-run dispatch helper for safe_op: builds DryRunResult + writes log event."""
    describe_fn = describe or (lambda kw: _default_describe(name, kw))
    dry = DryRunResult(
        tool_name=name,
        would_do=describe_fn(kwargs),
        params=sanitize_params(kwargs),
        timestamp=datetime.now(_ET).isoformat(),
    )
    write_event(
        log_path=log_target,
        tool_name=name,
        params=kwargs,
        result="dry_run",
        duration_ms=0,
    )
    return dry


def _execute_safe_op_call(fn, args, kwargs, name, log_target):
    """Real-call helper for safe_op: times the call, writes success/error log event.

    SafetyError propagates without a duplicate "error" log entry — the inner
    guard (safety_window / prod_guard) already wrote its specific block event.
    """
    start = time.monotonic()
    try:
        result = fn(*args, **kwargs)
    except SafetyError:
        raise
    except Exception:
        write_event(
            log_path=log_target,
            tool_name=name,
            params=kwargs,
            result="error",
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        raise
    write_event(
        log_path=log_target,
        tool_name=name,
        params=kwargs,
        result="success",
        duration_ms=int((time.monotonic() - start) * 1000),
    )
    return result


def safe_op(
    *,
    name: str,
    mutates: bool,
    describe: Optional[Callable[[dict[str, Any]], str]] = None,
    log_path: Optional[Union[Path, str]] = None,
):
    """Decorator: enforce dry-run defaulting + audit-log every call.

    For `mutates=True` tools: if `confirm=True` is NOT in the call kwargs,
    the wrapper returns a DryRunResult WITHOUT calling the wrapped function.
    Logs `dry_run`. Operator/agent must re-call with `confirm=True` to
    execute the real mutation.

    For `mutates=False` tools: the wrapper always calls the function and
    logs `success` / `error`.

    Args:
        name:     Identifier written to the audit log for this tool.
        mutates:  True for state-changing ops (restart, write, delete).
                  False for read-only ops (query, list).
        describe: Optional `(kwargs) -> str` for a tool-specific dry-run
                  description. Falls back to a generic template otherwise.
        log_path: Override the default audit log location (for tests).
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            log_target = Path(log_path) if log_path is not None else None
            if mutates and not kwargs.get("confirm", False):
                return _build_dry_run(name, kwargs, describe, log_target)
            return _execute_safe_op_call(fn, args, kwargs, name, log_target)

        return wrapper

    return decorator


# ═══════════════════════════════════════════════════════════════════
# Part 2 — SafetyWindowGuard
# ═══════════════════════════════════════════════════════════════════


def _now_et() -> datetime:
    """Default clock seam — current time in America/New_York.

    Pluggable: tests inject a lambda via the `now_et` decorator parameter
    to drive deterministic 'inside window' / 'outside window' scenarios.
    Mirrors the #97 lifecycle simulator's freezegun pattern.
    """
    return datetime.now(_ET)


def _parse_hhmm(s: str) -> tuple[int, int]:
    """'HH:MM' → (hour, minute). Already validated at config-load time."""
    hh, mm = s.split(":")
    return int(hh), int(mm)


def _in_window(now: datetime, start_et: str, end_et: str) -> bool:
    """Inclusive-start, exclusive-end. Handles cross-midnight windows.

    21:30-22:30 same-day: inside if start <= now < end.
    22:00-06:00 cross-midnight: inside if now >= start OR now < end.
    """
    sh, sm = _parse_hhmm(start_et)
    eh, em = _parse_hhmm(end_et)
    now_minutes = now.hour * 60 + now.minute
    start_minutes = sh * 60 + sm
    end_minutes = eh * 60 + em

    if start_minutes <= end_minutes:
        # Same-day window
        return start_minutes <= now_minutes < end_minutes
    # Cross-midnight: spans midnight (e.g., 22:00-06:00)
    return now_minutes >= start_minutes or now_minutes < end_minutes


def _handle_safety_window_call(fn, args, kwargs, window_name, now_et, config_path, log_target):
    """Per-call dispatch for safety_window: load window, check time, allow/block/bypass.

    Three outcomes:
      - inside window + no emergency → log "safety_window_block", raise SafetyWindowError
      - inside window + emergency=True → call fn, log "success" with emergency in params
        (audit trail for the bypass — grep-able later)
      - outside window → call fn silently (outer @safe_op layer logs the success)
    """
    cfg = load_arcis_config(path=config_path)
    window = cfg.safety_windows.get(window_name)
    if window is None:
        raise ValueError(
            f"safety_window: window {window_name!r} not declared in arcis_config.yaml"
        )

    inside_window = _in_window(now_et(), window.start_et, window.end_et)
    emergency = kwargs.get("emergency", False)

    if inside_window and not emergency:
        write_event(
            log_path=log_target,
            tool_name=fn.__name__,
            params=kwargs,
            result="safety_window_block",
            duration_ms=0,
        )
        raise SafetyWindowError(
            f"refusing call inside safety window {window_name!r} "
            f"({window.start_et}-{window.end_et} ET): {window.reason}. "
            "Pass emergency=True to override (logged)."
        )

    result = fn(*args, **kwargs)
    if inside_window and emergency:
        write_event(
            log_path=log_target,
            tool_name=fn.__name__,
            params=kwargs,
            result="success",
            duration_ms=0,
        )
    return result


def safety_window(
    window_name: str,
    *,
    now_et: Callable[[], datetime] = _now_et,
    log_path: Optional[Union[Path, str]] = None,
    config_path: Optional[Path] = None,
):
    """Decorator: refuse mutating op inside the named safety window.

    Reads the window definition (start_et, end_et, reason) from
    `arcis_config.yaml`'s `safety_windows.<window_name>` section. If
    `now_et()` falls inside the window AND the call doesn't pass
    `emergency=True`, raises SafetyWindowError and logs
    `safety_window_block`.

    Args:
        window_name: key under `safety_windows:` in arcis_config.yaml
        now_et:      pluggable clock seam (default: real ET time). Tests
                     inject a lambda for deterministic scenarios.
        log_path:    audit log override (for tests).
        config_path: arcis_config.yaml override (for tests).
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            log_target = Path(log_path) if log_path is not None else None
            return _handle_safety_window_call(
                fn, args, kwargs, window_name, now_et, config_path, log_target,
            )

        return wrapper

    return decorator


# ═══════════════════════════════════════════════════════════════════
# Part 3 — ProdGuard
# ═══════════════════════════════════════════════════════════════════


def _matches_prod_signature(dsn: str, signatures: list[str]) -> bool:
    return bool(dsn) and any(sig in dsn for sig in signatures)


def prod_guard(
    *,
    dsn_param: str,
    log_path: Optional[Union[Path, str]] = None,
    config_path: Optional[Path] = None,
):
    """Decorator: reject prod-signature DSN unless ARCIS_ALLOW_PROD_PG=1 AND confirm=True.

    Generalizes src/simulation/lifecycle/prod_guard.py's pattern from a
    monkeypatch-on-psycopg2 to a per-tool decorator. The signature list
    comes from `arcis_config.yaml`'s `pg.prod_dsn_signatures` (single
    source of truth shared with the simulator's _PROD_SIGNATURES).

    Args:
        dsn_param:   name of the kwarg containing the DSN string.
        log_path:    audit log override (for tests).
        config_path: arcis_config.yaml override (for tests).
    """
    import os

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            log_target = Path(log_path) if log_path is not None else None
            dsn = kwargs.get(dsn_param, "")

            cfg = load_arcis_config(path=config_path)
            if _matches_prod_signature(dsn, cfg.pg.prod_dsn_signatures):
                env_ok = os.environ.get("ARCIS_ALLOW_PROD_PG") == "1"
                confirmed = kwargs.get("confirm", False)
                if not (env_ok and confirmed):
                    write_event(
                        log_path=log_target,
                        tool_name=fn.__name__,
                        params=kwargs,
                        result="prod_guard_block",
                        duration_ms=0,
                    )
                    raise ProdGuardError(
                        f"refusing prod-PG DSN {sanitize_params({dsn_param: dsn})[dsn_param]!r} "
                        "without both ARCIS_ALLOW_PROD_PG=1 AND confirm=True. "
                        "(Both are required — env alone or confirm alone is rejected.)"
                    )

            return fn(*args, **kwargs)

        return wrapper

    return decorator
