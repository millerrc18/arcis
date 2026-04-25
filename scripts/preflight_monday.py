"""Monday morning go/no-go gate (audit-spec §9).

Validates the 10-item Pre-flight Monday Checklist for the 2026-04-27
trading-readiness audit. Exit 0 = all required checks pass (live capital
ramp eligible). Non-zero exit = at least one required check failed.

The script writes a human-readable transcript at
`audits/2026-04-27/preflight_transcript.txt` containing per-item PASS/FAIL,
evidence strings, and timestamps. Even on early failure, all 10 items
appear in the transcript (no silent skips).

CLI:
  python scripts/preflight_monday.py
  python scripts/preflight_monday.py --skip-alpaca-probe
  python scripts/preflight_monday.py --operator-email me@example.com

Exit codes:
  0  all required checks PASSED
  1  at least one required check FAILED

References:
  docs/audits/2026-04-27-trading-readiness/audit-spec.md §9
  T1.07 in plan.md
"""

from __future__ import annotations

import argparse
import importlib
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Spec cutoff for the pre-#651 sweep (audit-2026-04-27 §F-1).
# Any live shadow_trade row with created_at < this instant must be quarantined.
PRE_651_CUTOFF_ISO = "2026-04-22T00:00:00-04:00"

# Audit deliverable paths.
DEFAULT_MEMO_RELPATH = "audits/2026-04-27/stage1_baseline_memo.md"
DEFAULT_TRANSCRIPT_RELPATH = "audits/2026-04-27/preflight_transcript.txt"

_ET = ZoneInfo("America/New_York")


@dataclass
class CheckResult:
    """One row of the §9 checklist transcript."""
    name: str
    required: bool
    passed: bool
    evidence: str = ""
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _open_db():
    """Open a connection to the canonical SQLite DB. Indirected for tests."""
    from src.utils.db import connect_db
    return connect_db()


def check_pre_651_quarantine_clean(conn=None) -> CheckResult:
    """§9.1 — zero unquarantined live shadow_trades pre-cutoff."""
    name = "pre_651_quarantine_clean"
    own_conn = False
    try:
        if conn is None:
            conn = _open_db()
            own_conn = True
        row = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM shadow_trades
            WHERE source = 'live'
              AND COALESCE(quarantined, 0) = 0
              AND created_at < ?
            """,
            (PRE_651_CUTOFF_ISO,),
        ).fetchone()
        n = int(row["n"] if isinstance(row, dict) or hasattr(row, "keys") else row[0])
        passed = n == 0
        return CheckResult(
            name=name,
            required=True,
            passed=passed,
            evidence=f"unquarantined live pre-cutoff rows = {n} (cutoff={PRE_651_CUTOFF_ISO})",
        )
    except Exception as exc:
        return CheckResult(name=name, required=True, passed=False, error=str(exc))
    finally:
        if own_conn and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def check_quarantine_column_extended() -> CheckResult:
    """§9.1 — attribution_trades + walkforward_trades have `quarantined` col."""
    name = "quarantine_column_extended"
    try:
        from src.schema.registry import TABLES
        missing: list[str] = []
        present: list[str] = []
        for tname in ("attribution_trades", "walkforward_trades"):
            tdef = TABLES.get(tname)
            if tdef is None:
                missing.append(f"{tname}:table-missing")
                continue
            cols = {c.name for c in tdef.columns}
            if "quarantined" in cols:
                present.append(tname)
            else:
                missing.append(f"{tname}:no-quarantined-col")
        passed = not missing
        ev = f"present={present} missing={missing}"
        return CheckResult(name=name, required=True, passed=passed, evidence=ev)
    except Exception as exc:
        return CheckResult(name=name, required=True, passed=False, error=str(exc))


def check_canonical_sharpe_module_exists(repo_root: Path) -> CheckResult:
    """§9.2 — src/analytics/canonical_sharpe.py exists (T1.03 product)."""
    name = "canonical_sharpe_module_exists"
    target = Path(repo_root) / "src" / "analytics" / "canonical_sharpe.py"
    passed = target.is_file()
    return CheckResult(
        name=name,
        required=True,
        passed=passed,
        evidence=f"path={target} exists={passed}",
    )


def check_governor_enabled(config: dict) -> CheckResult:
    """§9.4 — risk_governor.enabled == True."""
    name = "governor_enabled"
    val = (config.get("risk_governor", {}) or {}).get("enabled", None)
    passed = val is True
    return CheckResult(
        name=name,
        required=True,
        passed=passed,
        evidence=f"risk_governor.enabled={val!r}",
    )


def check_capital_cap(config: dict) -> CheckResult:
    """§3.1 — live_trading.starting_capital == 100."""
    name = "capital_cap"
    val = (config.get("live_trading", {}) or {}).get("starting_capital", None)
    passed = val == 100
    return CheckResult(
        name=name,
        required=True,
        passed=passed,
        evidence=f"live_trading.starting_capital={val!r} (expected 100)",
    )


def check_effective_position_cap(config: dict) -> CheckResult:
    """§9.3 — effective_position_cap helper returns > 0."""
    name = "effective_position_cap"
    try:
        from src.risk.governor import effective_position_cap
        cap = effective_position_cap(config)
        passed = isinstance(cap, int) and cap > 0
        return CheckResult(
            name=name,
            required=True,
            passed=passed,
            evidence=f"effective_position_cap={cap}",
        )
    except Exception as exc:
        return CheckResult(name=name, required=True, passed=False, error=str(exc))


def check_mr_bracket_config(config: dict) -> CheckResult:
    """§9.6 — strategies.mean_reversion.stop_atr_multiple set + template importable."""
    name = "mr_bracket_config"
    mr_cfg = (config.get("strategies", {}) or {}).get("mean_reversion", {}) or {}
    stop_mult = mr_cfg.get("stop_atr_multiple")
    has_value = isinstance(stop_mult, (int, float)) and not isinstance(stop_mult, bool)
    template_ok = False
    template_err: Optional[str] = None
    try:
        # importlib.import_module raises if module is None in sys.modules.
        mod = importlib.import_module("src.packets.template")
        if mod is None:
            template_err = "src.packets.template resolves to None"
        else:
            template_ok = True
    except Exception as exc:
        template_err = str(exc)
    passed = has_value and template_ok
    ev_parts = [f"stop_atr_multiple={stop_mult!r}"]
    if template_ok:
        ev_parts.append("template-importable")
    else:
        ev_parts.append(f"template-import-failed:{template_err}")
    return CheckResult(
        name=name,
        required=True,
        passed=passed,
        evidence=" ".join(ev_parts),
        error=template_err if not template_ok else None,
    )


def check_alpaca_connectivity(config: dict, skip: bool = False) -> CheckResult:
    """§9.7 — Alpaca REST probe via broker_factory.get_live_broker.get_account.

    Skippable via --skip-alpaca-probe. When skipped, records FAIL with a
    skip reason so the operator sees an audit trail.
    """
    name = "alpaca_connectivity"
    if skip:
        return CheckResult(
            name=name,
            required=True,
            passed=False,
            evidence="alpaca probe skipped via --skip-alpaca-probe",
            error="skipped",
        )
    try:
        # Local import so monkeypatch of src.trading.broker_factory.get_live_broker
        # works in tests (the symbol is looked up at call time, not import time).
        import src.trading.broker_factory as bf
        broker = bf.get_live_broker(config)
        acct = broker.get_account()
        passed = acct is not None
        return CheckResult(
            name=name,
            required=True,
            passed=passed,
            evidence=f"get_account() -> {type(acct).__name__ if acct is not None else 'None'}",
        )
    except Exception as exc:
        return CheckResult(name=name, required=True, passed=False, error=str(exc))


def _signed_off_emails(commit_body: str) -> list[str]:
    """Return list of email addresses from `Signed-off-by:` trailers."""
    pat = re.compile(r"^Signed-off-by:\s*.+?<([^>]+)>", re.MULTILINE)
    return [m.group(1).strip() for m in pat.finditer(commit_body)]


def check_baseline_memo_signed_off(
    repo_root: Path,
    memo_relpath: str,
    operator_email: Optional[str],
) -> CheckResult:
    """§9.9 — memo file exists + HEAD commit touching it has Signed-off-by trailer.

    operator_email semantics:
      None        -> require trailer to match git config user.email
      ''          -> any Signed-off-by trailer is accepted
      'foo@bar'   -> trailer must match exactly
    """
    name = "baseline_memo_signed_off"
    repo_root = Path(repo_root)
    memo_path = repo_root / memo_relpath
    if not memo_path.is_file():
        return CheckResult(
            name=name,
            required=True,
            passed=False,
            evidence=f"memo missing at {memo_path}",
        )
    try:
        # git log -1 --format=%H%n%B -- <path>
        result = subprocess.run(
            ["git", "-C", str(repo_root), "log", "-1", "--format=%H%n%B", "--", memo_relpath],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return CheckResult(
                name=name,
                required=True,
                passed=False,
                error=f"git log failed: {result.stderr.strip()}",
            )
        out = result.stdout.strip()
        if not out:
            return CheckResult(
                name=name,
                required=True,
                passed=False,
                evidence=f"no commit touches {memo_relpath}",
            )
        lines = out.split("\n", 1)
        sha = lines[0]
        body = lines[1] if len(lines) > 1 else ""
        trailers = _signed_off_emails(body)
        if not trailers:
            return CheckResult(
                name=name,
                required=True,
                passed=False,
                evidence=f"commit {sha[:8]} has no Signed-off-by trailer",
            )
        # Determine the expected operator email.
        if operator_email is None:
            # Fallback to git config user.email at the repo root.
            cfg = subprocess.run(
                ["git", "-C", str(repo_root), "config", "user.email"],
                capture_output=True,
                text=True,
            )
            expected = cfg.stdout.strip() if cfg.returncode == 0 else ""
        else:
            expected = operator_email
        if expected == "":
            return CheckResult(
                name=name,
                required=True,
                passed=True,
                evidence=f"commit {sha[:8]} signed-off-by={trailers} (any-trailer-accepted)",
            )
        if expected in trailers:
            return CheckResult(
                name=name,
                required=True,
                passed=True,
                evidence=f"commit {sha[:8]} signed-off-by={expected}",
            )
        return CheckResult(
            name=name,
            required=True,
            passed=False,
            evidence=f"commit {sha[:8]} trailers={trailers} expected={expected!r}",
        )
    except FileNotFoundError as exc:
        return CheckResult(name=name, required=True, passed=False, error=f"git not found: {exc}")
    except Exception as exc:
        return CheckResult(name=name, required=True, passed=False, error=str(exc))


# ---------------------------------------------------------------------------
# Transcript writer
# ---------------------------------------------------------------------------


def write_transcript(out_path: Path, results: list[CheckResult]) -> None:
    """Write a human-readable transcript with timestamps + per-check status."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    now_et = datetime.now(_ET).isoformat(timespec="seconds")
    lines: list[str] = []
    lines.append("Pre-flight Monday Checklist (audit-spec §9)")
    lines.append(f"Generated: {now_et}")
    lines.append("=" * 72)
    lines.append("")
    n_pass = sum(1 for r in results if r.passed)
    n_fail = sum(1 for r in results if not r.passed)
    lines.append(f"Summary: {n_pass} PASS / {n_fail} FAIL ({len(results)} total)")
    lines.append("")
    for i, r in enumerate(results, start=1):
        status = "PASS" if r.passed else "FAIL"
        ts = datetime.now(_ET).isoformat(timespec="seconds")
        required = "required" if r.required else "optional"
        lines.append(f"[{i:>2}] [{ts}] {status} ({required}) {r.name}")
        if r.evidence:
            lines.append(f"     evidence: {r.evidence}")
        if r.error:
            lines.append(f"     error: {r.error}")
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _resolve_operator_email(repo_root: Path, supplied: Optional[str]) -> Optional[str]:
    """Resolve operator email for the memo trailer check.

    Order:
      1. CLI --operator-email if provided
      2. `git config user.email` at repo_root
      3. None -> caller treats as "no expectation set"
    """
    if supplied is not None:
        return supplied
    try:
        cfg = subprocess.run(
            ["git", "-C", str(repo_root), "config", "user.email"],
            capture_output=True,
            text=True,
        )
        if cfg.returncode == 0:
            email = cfg.stdout.strip()
            if email:
                return email
    except Exception:
        pass
    return None


def main(argv: Optional[list[str]] = None, config: Optional[dict] = None) -> int:
    """Run all 10 §9 checks and write the transcript. Return exit code."""
    parser = argparse.ArgumentParser(description="Monday go/no-go gate (audit-spec §9)")
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root containing audits/ and src/",
    )
    parser.add_argument(
        "--memo",
        default=DEFAULT_MEMO_RELPATH,
        help="Stage 1 baseline memo path relative to repo root",
    )
    parser.add_argument(
        "--transcript",
        default=None,
        help="Output transcript path. Defaults to <repo-root>/audits/2026-04-27/preflight_transcript.txt",
    )
    parser.add_argument(
        "--operator-email",
        default=None,
        help="Email to match against Signed-off-by trailer. Empty string accepts any trailer.",
    )
    parser.add_argument(
        "--skip-alpaca-probe",
        action="store_true",
        help="Skip the Alpaca REST probe (records FAIL with skip-reason).",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    transcript_path = (
        Path(args.transcript)
        if args.transcript is not None
        else repo_root / DEFAULT_TRANSCRIPT_RELPATH
    )

    if config is None:
        from src.config import load_config
        config = load_config()

    # Resolve operator email — None means caller didn't supply.
    operator_email = (
        args.operator_email
        if args.operator_email is not None
        else _resolve_operator_email(repo_root, None)
    )

    results: list[CheckResult] = []

    # 1. pre-#651 quarantine clean
    results.append(check_pre_651_quarantine_clean())
    # 2. quarantined column on attribution + walkforward
    results.append(check_quarantine_column_extended())
    # 3. canonical_sharpe.py exists (T1.03)
    results.append(check_canonical_sharpe_module_exists(repo_root))
    # 4. governor enabled
    results.append(check_governor_enabled(config))
    # 5. capital cap == 100
    results.append(check_capital_cap(config))
    # 6. effective_position_cap > 0
    results.append(check_effective_position_cap(config))
    # 7. MR bracket config + template importable
    results.append(check_mr_bracket_config(config))
    # 8. Alpaca REST probe (skippable)
    results.append(check_alpaca_connectivity(config, skip=args.skip_alpaca_probe))
    # 9. baseline memo signed off
    results.append(
        check_baseline_memo_signed_off(repo_root, args.memo, operator_email)
    )
    # 10. transcript saved (always passes once we write it below)
    results.append(
        CheckResult(
            name="transcript_saved",
            required=True,
            passed=True,
            evidence=f"path={transcript_path}",
        )
    )

    write_transcript(transcript_path, results)

    failed_required = [r for r in results if r.required and not r.passed]
    return 0 if not failed_required else 1


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )
    sys.exit(main())
