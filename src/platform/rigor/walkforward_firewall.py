"""R8 strategy identity firewall + bootcamp-off + runtime heuristic.

Called by: src.platform.rigor.walkforward_runner.
Calls: datetime, subprocess (git log lookup for heuristic), re.
Owns tables: none.
Config keys: none.
Tests: tests/platform/rigor/test_walkforward_firewall.py.

R8 clauses:

  (a) `derived_from` is a REQUIRED key on every spec (value may be None).
      Structure when non-None:
        source_type: 'forensic_audit_ruleset' | 'bootcamp_backtest' |
                     'shadow_trading_cohort' | 'other'
        source_run_id: str
        source_trade_ids: optional list[str]
        source_date_range: {start: ISO, end: ISO}

  (b) Overlap assertion: for each source_date_range, it must have ZERO
      overlap with ANY OOS window.

  (c) No inherited credit — enforced by the runner; this module validates
      the declared provenance but does not import source metrics.

  (d) Bootcamp forced False during walk-forward (defense-in-depth assertion).

  (e) PR body declaration — honor-system, verified by reviewers.

Runtime heuristic (non-blocking): emits a WARNING when the spec file's
git-history first commit is within 30 days of a forensic-audit run on the
same strategy family AND `derived_from == null`. The operator may ignore
the warning, but it surfaces the case where a developer produces a spec
shortly after an audit and claims no derivation.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

logger = logging.getLogger(__name__)


class R8ViolationError(RuntimeError):
    """Raised when R8 is violated — zero partial results are written."""


ALLOWED_SOURCE_TYPES = frozenset({
    "forensic_audit_ruleset", "bootcamp_backtest",
    "shadow_trading_cohort", "other",
})
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SOURCE_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


@dataclass
class Window:
    """Minimal window shape for overlap assertion. Matches
    WalkForwardWindow.test_start/test_end but avoids circular import."""

    test_start: str
    test_end: str


def _is_iso(s) -> bool:
    if not isinstance(s, str):
        return False
    if not _ISO_RE.match(s):
        return False
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def validate_derived_from(spec_raw: dict) -> None:
    """R8(a): raise if the required `derived_from` field is missing or
    malformed. A value of None (explicit null) is legal and means "no
    known derivation".
    """
    if "derived_from" not in spec_raw:
        raise R8ViolationError(
            "R8(a) violation: strategy spec missing required 'derived_from' "
            "field. Use 'derived_from: null' for organic/literature-derived "
            "strategies."
        )
    df = spec_raw["derived_from"]
    if df is None:
        return
    if not isinstance(df, dict):
        raise R8ViolationError(
            f"R8(a) violation: derived_from must be null or a dict, got "
            f"{type(df).__name__}"
        )
    if df.get("source_type") not in ALLOWED_SOURCE_TYPES:
        raise R8ViolationError(
            f"R8(a) violation: derived_from.source_type must be one of "
            f"{sorted(ALLOWED_SOURCE_TYPES)}, got {df.get('source_type')!r}"
        )
    sri = df.get("source_run_id")
    if not isinstance(sri, str) or not _SOURCE_RUN_ID_RE.match(sri):
        raise R8ViolationError(
            "R8(a) violation: derived_from.source_run_id must be a "
            "non-empty identifier string (alphanumeric + _-.)."
        )
    sdr = df.get("source_date_range")
    if not isinstance(sdr, dict):
        raise R8ViolationError(
            "R8(a) violation: derived_from.source_date_range must be a "
            "dict with start+end keys."
        )
    for key in ("start", "end"):
        if not _is_iso(sdr.get(key)):
            raise R8ViolationError(
                f"R8(a) violation: derived_from.source_date_range.{key} "
                f"must be ISO yyyy-mm-dd; got {sdr.get(key)!r}"
            )
    if sdr["start"] > sdr["end"]:
        raise R8ViolationError(
            f"R8(a) violation: derived_from.source_date_range.start "
            f"({sdr['start']}) > end ({sdr['end']})"
        )
    # source_trade_ids is optional but must be list[str] if present.
    if "source_trade_ids" in df:
        sti = df["source_trade_ids"]
        if not isinstance(sti, list) or not all(isinstance(x, str) for x in sti):
            raise R8ViolationError(
                "R8(a) violation: derived_from.source_trade_ids must be "
                "a list of strings when present."
            )


def _overlaps(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    """Two closed intervals overlap iff start_a <= end_b and start_b <= end_a."""
    return a_start <= b_end and b_start <= a_end


def assert_no_overlap(
    derived_from: dict | None,
    windows: Iterable[Window],
) -> None:
    """R8(b): reject any run whose source_date_range overlaps any OOS window.
    No-op if derived_from is None (R8(b) note in spec)."""
    if derived_from is None:
        return
    sdr = derived_from.get("source_date_range")
    if sdr is None:
        return
    s_start, s_end = sdr["start"], sdr["end"]
    for w in windows:
        if _overlaps(w.test_start, w.test_end, s_start, s_end):
            raise R8ViolationError(
                f"R8(b) violation: source_date_range [{s_start}, {s_end}] "
                f"overlaps OOS window [{w.test_start}, {w.test_end}]. "
                f"Walk-forward requires zero overlap — the source data "
                f"leaks into OOS."
            )


def ensure_bootcamp_off(bootcamp_override: bool) -> None:
    """R8(d): belt-and-suspenders assertion. WalkForwardConfig already
    raises in __post_init__ when bootcamp_override=True. This function
    is the runner-time double-check; keep both so removal of one does
    not break R8(d)."""
    if bootcamp_override is True:
        raise R8ViolationError(
            "R8(d) violation: bootcamp_override must be False during walk-"
            "forward. Set WalkForwardConfig.bootcamp_override=False "
            "(it is False by default)."
        )


def _first_commit_date_for_path(repo_root: str, path: str) -> date | None:
    """Return the ISO date of the first git commit that introduced `path`,
    or None if unavailable (path not tracked, git not available, etc.).
    """
    try:
        out = subprocess.check_output(
            ["git", "-C", repo_root, "log", "--diff-filter=A", "--format=%ad",
             "--date=short", "--reverse", "--", path],
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None
    lines = [ln.strip() for ln in out.decode().splitlines() if ln.strip()]
    if not lines:
        return None
    try:
        return date.fromisoformat(lines[0])
    except ValueError:
        return None


def check_provenance_heuristic(
    spec_path: str | None,
    spec_raw: dict,
    forensic_audits: Iterable[dict],
    repo_root: str = ".",
    window_days: int = 30,
) -> list[str]:
    """Non-blocking runtime heuristic for suspicious derived_from: null.

    Args:
        spec_path: absolute or relative path to the spec YAML. If None or
                   the git lookup fails, the heuristic is a no-op.
        spec_raw: loaded YAML as a dict.
        forensic_audits: iterable of dicts with 'strategy_family' (str) and
                         'completed_at' (ISO date string) keys. Usually
                         loaded from the forensic_audits runs table, but we
                         accept an iterable so tests can inject synthetic
                         rows.
        repo_root: directory to run git in.
        window_days: days from audit completion date.

    Returns:
        list[str] of warning messages. An empty list means no suspicion.
        The runner prints these as WARNINGs and continues.
    """
    warnings: list[str] = []
    if spec_raw.get("derived_from") is not None:
        return warnings  # explicit derivation declared — no suspicion
    if not spec_path:
        return warnings
    first_commit = _first_commit_date_for_path(repo_root, spec_path)
    if first_commit is None:
        return warnings
    strategy_id = str(spec_raw.get("strategy_id", ""))
    family_prefix = strategy_id.rsplit("_", 1)[0] or strategy_id
    for audit in forensic_audits:
        fam = str(audit.get("strategy_family", ""))
        completed_raw = audit.get("completed_at")
        if not fam or not completed_raw:
            continue
        if family_prefix and not (family_prefix == fam or family_prefix.startswith(fam)):
            continue
        try:
            completed = date.fromisoformat(str(completed_raw)[:10])
        except ValueError:
            continue
        delta = abs((first_commit - completed).days)
        if delta <= window_days:
            warnings.append(
                f"R8 runtime heuristic: spec {spec_path} first committed "
                f"{first_commit.isoformat()} is within {window_days}d of "
                f"forensic audit {audit.get('audit_id', 'unknown')} on "
                f"family {fam!r} (completed {completed.isoformat()}) and "
                f"declares derived_from: null. Verify the ruleset was not "
                f"fitted to the audited trades."
            )
    return warnings
