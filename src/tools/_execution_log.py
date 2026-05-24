"""JSON-lines tool-call audit log — writes every tool invocation.

Per #104 (v0.36.57): all tool calls (success / dry_run / blocked / error)
land in `data/logs/tool-execution.log` as one JSON event per line.

Log location matches the operator's preference (co-located with NSSM
service logs at `data/logs/`) — single answer to "where do I find logs?".

Why JSON-lines (not text):
    grep-able + future-parseable by #111's periodic skill-audit. The
    skill-audit will compute per-tool usage stats, identify unused
    tools, and surface "tools that blocked X times — operator should
    revisit them."

Why per-call rotation at 10MB:
    Mirrors NSSM service log rotation. Operator's mental model: any
    log file in data/logs/ tops out around 10MB then rotates to `.1`,
    one keep-back. Same here.

Called by: src.tools._safety primitives (SafeOp, SafetyWindowGuard, ProdGuard)
Calls: pathlib, json, datetime
Owns tables: none
Config keys: none (log path passed by caller, defaults to data/logs/)
Tests: tests/tools/test_execution_log.py
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo


# ── Constants ─────────────────────────────────────────────────────────

ROTATE_BYTES = 10 * 1024 * 1024  # 10 MB; mirrors NSSM rotation policy

_ET = ZoneInfo("America/New_York")

# Repo-relative default log path. Tools can override via the log_path
# parameter, but the default is the operator's standard location.
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_PATH = _REPO_ROOT / "data" / "logs" / "tool-execution.log"

# Result kinds accepted by write_event. Documented in the docstring so
# future tools have a closed enumeration to choose from.
_VALID_RESULTS = frozenset({
    "success",
    "dry_run",
    "safety_window_block",
    "prod_guard_block",
    "error",
})

# Substring patterns that mark a kwarg as a secret. Case-insensitive
# match on the KEY (not the value) — the value is replaced with "REDACTED"
# wholesale. Conservative list; add patterns as new secret-shaped keys
# appear in tool APIs.
_SECRET_KEY_PATTERNS = re.compile(
    r"(password|secret|token|api[_-]?key|bot_token|access[_-]?key)",
    re.IGNORECASE,
)

# DSN-shaped values get partial redaction (preserve host/db for diagnostics).
# Pattern: `scheme://user:PASSWORD@host...` → `scheme://user:REDACTED@host...`
_DSN_PASSWORD_RE = re.compile(r"(://[^:/?@\s]+):[^@\s]+@")


# ── Sanitization ─────────────────────────────────────────────────────


def _sanitize_dsn(dsn: str) -> str:
    """Partial-redact DSN: preserve scheme/user/host/db, redact password."""
    return _DSN_PASSWORD_RE.sub(r"\1:REDACTED@", dsn)


def sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of `params` with secrets removed.

    Two redaction rules:
      1. Key matches _SECRET_KEY_PATTERNS → value replaced with "REDACTED"
         wholesale (no useful diagnostic info in api keys, tokens, etc.).
      2. Value is a DSN-shaped string (contains `://...:...@`) → partial
         redact via _sanitize_dsn (preserve host/db for diagnostics).

    The original dict is NOT mutated — callers get a fresh dict safe to
    log without disturbing the underlying tool's runtime state.
    """
    clean: dict[str, Any] = {}
    for k, v in params.items():
        if _SECRET_KEY_PATTERNS.search(k):
            # Special-case `database_url`-style DSN fields: preserve host/db.
            # If the value LOOKS like a DSN, partial-redact; else full redact.
            if isinstance(v, str) and "://" in v and "@" in v:
                clean[k] = _sanitize_dsn(v)
            else:
                clean[k] = "REDACTED"
        elif isinstance(v, str) and _DSN_PASSWORD_RE.search(v):
            # Non-secret-keyed but DSN-shaped value (e.g., a `dsn` kwarg) —
            # partial redact for diagnostics.
            clean[k] = _sanitize_dsn(v)
        else:
            clean[k] = v
    return clean


# ── Rotation ─────────────────────────────────────────────────────────


def _should_rotate(log_path: Path) -> bool:
    return log_path.exists() and log_path.stat().st_size >= ROTATE_BYTES


def _rotate(log_path: Path) -> None:
    """Move log_path → log_path.1, replacing any existing .1 (one keep-back)."""
    rotated = log_path.with_suffix(log_path.suffix + ".1")
    if rotated.exists():
        rotated.unlink()
    log_path.rename(rotated)


# ── Public API ───────────────────────────────────────────────────────


def write_event(
    *,
    log_path: Optional[Path] = None,
    tool_name: str,
    params: dict[str, Any],
    result: str,
    duration_ms: int,
    session_id: Optional[str] = None,
) -> None:
    """Append a single JSON event to the tool-execution log.

    Args:
        log_path:   Override the default location (DEFAULT_LOG_PATH). Tests
                    pass a tmp_path here; tools call with no argument.
        tool_name:  Identifier for the tool that was invoked (e.g. "nssm_restart").
        params:     Tool kwargs; sanitized for secrets before write.
        result:     One of _VALID_RESULTS — see module docstring.
        duration_ms: Wall-clock duration of the tool call (ms).
        session_id: Optional caller-supplied agent/session identifier.

    The event JSON shape:
        {
          "timestamp": "2026-05-24T14:32:01.123456-04:00",  # ISO 8601 + ET offset
          "tool_name": "...",
          "params": {...},                                   # sanitized
          "result": "success",
          "duration_ms": 42,
          "session_id": "..."                                # only if provided
        }
    """
    if result not in _VALID_RESULTS:
        raise ValueError(
            f"invalid result {result!r}; expected one of {sorted(_VALID_RESULTS)}"
        )

    target = log_path if log_path is not None else DEFAULT_LOG_PATH

    # Ensure parent dir exists (tests use tmp_path which already exists;
    # production may hit a fresh deploy without data/logs/ yet).
    target.parent.mkdir(parents=True, exist_ok=True)

    if _should_rotate(target):
        _rotate(target)

    event: dict[str, Any] = {
        "timestamp": datetime.now(_ET).isoformat(),
        "tool_name": tool_name,
        "params": sanitize_params(params),
        "result": result,
        "duration_ms": duration_ms,
    }
    if session_id is not None:
        event["session_id"] = session_id

    # Append one JSON-line. `default=str` is a safety net for non-JSON-native
    # types in params (e.g., Path objects); they serialize as their repr.
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str) + "\n")
