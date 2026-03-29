#!/usr/bin/env python3
"""Run a daily repo audit with baseline-aware classification.

This script is designed for GitHub Actions, but it also runs locally.
It focuses on repo-level correctness and contract checks rather than
machine-specific runtime services such as Ollama or Alpaca availability.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE_PATH = ROOT / "config" / "daily_repo_audit_baseline.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    title: str
    command: str
    runner: Callable[[], tuple[bool, str]]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _tail(text: str, lines: int = 40, chars: int = 6000) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    parts = text.splitlines()
    trimmed = "\n".join(parts[-lines:])
    if len(trimmed) > chars:
        trimmed = trimmed[-chars:]
    return trimmed


def _run_subprocess(command: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    output = "\n".join(
        part for part in [proc.stdout.strip(), proc.stderr.strip()] if part
    ).strip()
    return proc.returncode == 0, output


def _cleanup_temp_path(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        # Windows can briefly retain sqlite handles after close; keep the audit result.
        pass


def _build_trade_packet():
    from src.schemas import PositionSizing, TradePacket

    return TradePacket(
        ticker="AAPL",
        company_name="Apple Inc.",
        recommendation="BUY",
        setup_type="pullback",
        why_now="Daily audit probe",
        entry_zone="$100 area",
        stop_invalidation="$95 close basis",
        targets="$110 / $120",
        expected_hold_period="2-5 days",
        confidence=7,
        event_risk="Normal",
        position_sizing=PositionSizing(
            allocation_dollars=3000.0,
            allocation_pct=3.0,
            estimated_risk_dollars=150.0,
        ),
        deeper_analysis="Daily audit probe",
        llm_conviction=7,
    )


def _validator_real_packet_probe() -> tuple[bool, str]:
    from src.llm.validator import validate_llm_output

    packet = _build_trade_packet()
    features = {"current_price": 100.0}
    config = {"risk": {"starting_capital": 100000}}

    try:
        with patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL"]):
            is_valid, reason = validate_llm_output(packet, features, config)
    except Exception as exc:
        return False, f"validate_llm_output raised {type(exc).__name__}: {exc}"

    if not is_valid:
        return False, f"validator rejected a safe packet: {reason}"

    return True, "validator accepted a real TradePacket with string execution fields"


def _live_guard_fail_closed_probe() -> tuple[bool, str]:
    from src.shadow_trading.executor import open_live_trade

    packet = _build_trade_packet()
    features = {
        "atr_14": 2.0,
        "_score": 80,
        "setup_type": "pullback",
        "setup_confidence": 0.8,
    }
    config = {
        "live_trading": {
            "enabled": True,
            "starting_capital": 100.0,
            "max_open_positions": 2,
            "risk": {
                "planned_risk_pct_max": 0.02,
                "stop_atr_multiplier": 1.0,
                "target_atr_multiplier": 2.0,
                "timeout_days": 7,
            },
        }
    }

    with patch("src.shadow_trading.executor.load_config", return_value=config), patch(
        "src.shadow_trading.alpaca_adapter.get_live_account_info",
        return_value={"equity": 1000.0, "buying_power": 1000.0},
    ), patch(
        "src.journal.store.get_open_shadow_trades",
        side_effect=Exception("db locked"),
    ), patch(
        "src.shadow_trading.alpaca_adapter.place_live_entry",
        return_value={"order_id": "order-1", "filled_avg_price": 100.0},
    ) as place_live_entry, patch(
        "src.shadow_trading.executor.insert_shadow_trade", return_value="trade-1"
    ), patch("src.notifications.telegram.is_telegram_enabled", return_value=False):
        trade_id = open_live_trade("rec-1", packet, features, db_path=":memory:")

    if trade_id is not None or place_live_entry.called:
        return (
            False,
            "open_live_trade continued toward broker submission after state-query failure",
        )

    return True, "live trading failed closed when safety-state queries raised"


def _live_close_broker_truth_probe() -> tuple[bool, str]:
    from src.journal.store import initialize_database
    from src.shadow_trading.executor import check_and_manage_open_trades

    fd, raw_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    db_path = Path(raw_path)

    try:
        initialize_database(str(db_path))
        now = _utc_now().isoformat()
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO shadow_trades (
                    trade_id, recommendation_id, ticker, direction, status,
                    entry_price, stop_price, target_1, target_2, planned_shares,
                    planned_allocation, actual_entry_price, actual_entry_time,
                    created_at, updated_at, source, order_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "trade-1",
                    None,
                    "AAPL",
                    "long",
                    "open",
                    100.0,
                    95.0,
                    110.0,
                    120.0,
                    1,
                    100.0,
                    100.0,
                    now,
                    now,
                    now,
                    "live",
                    "simple",
                ),
            )
            conn.commit()

        with patch(
            "src.shadow_trading.executor._get_current_price_safe", return_value=94.0
        ), patch(
            "src.shadow_trading.alpaca_adapter.place_paper_exit", return_value={}
        ), patch(
            "src.shadow_trading.alpaca_adapter.place_live_exit",
            side_effect=Exception("live broker failed"),
        ), patch(
            "src.notifications.telegram.is_telegram_enabled", return_value=False
        ), patch(
            "src.shadow_trading.executor._check_close_milestones", return_value=None
        ), patch(
            "src.shadow_trading.executor._check_loss_streak", return_value=None
        ):
            check_and_manage_open_trades(db_path=str(db_path), source_filter="live")

        with sqlite3.connect(db_path) as conn:
            status = conn.execute(
                "SELECT status FROM shadow_trades WHERE trade_id = ?", ("trade-1",)
            ).fetchone()[0]

        if status != "open":
            return (
                False,
                "live trade was marked closed locally even though live broker exit failed",
            )

        return True, "live trade remained open when broker exit failed"
    finally:
        _cleanup_temp_path(db_path)


def _local_shadow_close_live_guard_probe() -> tuple[bool, str]:
    from src.api.routes.shadow import close_trade

    now = _utc_now().isoformat()
    trade = {
        "trade_id": "trade-1",
        "ticker": "AAPL",
        "source": "live",
        "planned_shares": 1,
        "actual_entry_price": 100.0,
        "entry_price": 100.0,
        "created_at": now,
        "actual_entry_time": now,
        "recommendation_id": None,
    }

    with patch("src.journal.store.get_open_shadow_trades", return_value=[trade]), patch(
        "src.journal.store.close_shadow_trade"
    ) as close_shadow_trade, patch(
        "src.journal.store.update_shadow_trade"
    ), patch(
        "src.journal.store.update_recommendation"
    ), patch(
        "src.shadow_trading.executor._get_current_price_safe", return_value=95.0
    ):
        result = close_trade("AAPL")

    if "error" not in result or close_shadow_trade.called:
        return (
            False,
            "local close route accepted a live trade and attempted to close it locally",
        )

    return True, "local close route blocked live trade closure without broker flow"


def _paper_entry_requires_broker_probe() -> tuple[bool, str]:
    from src.journal.store import initialize_database
    from src.shadow_trading.executor import open_shadow_trade

    fd, raw_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    db_path = Path(raw_path)

    try:
        initialize_database(str(db_path))
        packet = _build_trade_packet()
        features = {
            "current_price": 100.0,
            "event_risk_level": "none",
            "traffic_light_multiplier": 1.0,
        }
        config = {
            "shadow_trading": {"enabled": True, "max_positions": 10, "timeout_days": 15},
            "risk": {"starting_capital": 100000},
        }

        with patch("src.shadow_trading.executor.load_config", return_value=config), patch(
            "src.llm.validator.validate_llm_output", return_value=(True, "passed")
        ), patch(
            "src.risk.governor.get_portfolio_state",
            return_value={
                "equity": 100000.0,
                "open_count": 0,
                "open_positions": [],
                "sector_exposure": {},
                "daily_pnl_pct": 0.0,
            },
        ), patch(
            "src.risk.governor.RiskGovernor.check_trade",
            return_value={"approved": True, "checks": []},
        ), patch(
            "src.shadow_trading.executor.get_open_shadow_trades", return_value=[]
        ), patch(
            "src.shadow_trading.executor.get_open_shadow_trade_for_ticker",
            return_value=None,
        ), patch(
            "src.shadow_trading.alpaca_adapter.place_bracket_order",
            side_effect=Exception("bracket failed"),
        ), patch(
            "src.shadow_trading.alpaca_adapter.place_paper_entry",
            side_effect=Exception("simple order failed"),
        ), patch(
            "src.shadow_trading.executor._check_open_milestones", return_value=None
        ), patch(
            "src.shadow_trading.executor._check_sector_exposure", return_value=None
        ):
            trade_id = open_shadow_trade("rec-1", packet, features, db_path=str(db_path))

        with sqlite3.connect(db_path) as conn:
            open_count = conn.execute(
                "SELECT COUNT(*) FROM shadow_trades WHERE status = 'open'"
            ).fetchone()[0]

        if trade_id is not None or open_count != 0:
            return (
                False,
                "paper trade was recorded locally even though both broker submission paths failed",
            )

        return True, "paper trade was not recorded when broker submission failed"
    finally:
        _cleanup_temp_path(db_path)


def _council_schema_probe() -> tuple[bool, str]:
    from src.council.agents import gather_macro_data, gather_tactical_data
    from src.council.protocol import build_shared_context
    from src.data_collection.macro_collector import _init_table as init_macro_table
    from src.data_collection.vix_collector import _init_table as init_vix_table
    from src.journal.store import initialize_database
    from src.training.versioning import init_training_tables

    fd, raw_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    db_path = Path(raw_path)

    try:
        initialize_database(str(db_path))
        init_training_tables(str(db_path))
        init_vix_table(str(db_path))
        init_macro_table(str(db_path))

        now = _utc_now()
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO recommendations (
                    recommendation_id, created_at, ticker, company_name, priority_score
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ("rec-1", now.isoformat(), "AAPL", "Apple Inc.", 80.0),
            )
            conn.execute(
                """
                INSERT INTO vix_term_structure (
                    collected_at, collected_date, vix, vix9d, vix3m, vix1y,
                    term_structure_slope, near_term_ratio
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now.isoformat(),
                    now.strftime("%Y-%m-%d"),
                    20.0,
                    21.0,
                    19.0,
                    18.0,
                    1.05,
                    1.05,
                ),
            )
            macro_rows = [
                ("DFF", "Fed Funds Rate", 4.5),
                ("T10Y2Y", "10Y-2Y Spread", -0.3),
                ("T10Y3M", "10Y-3M Spread", -0.1),
                ("BAMLH0A0HYM2", "HY Spread (OAS)", 4.2),
                ("UNRATE", "Unemployment", 4.0),
            ]
            for series_id, series_name, value in macro_rows:
                conn.execute(
                    """
                    INSERT INTO macro_snapshots (
                        collected_at, collected_date, series_id, series_name,
                        value, previous_value, change_pct
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now.isoformat(),
                        now.strftime("%Y-%m-%d"),
                        series_id,
                        series_name,
                        value,
                        value,
                        0.0,
                    ),
                )
            conn.commit()

        tactical = gather_tactical_data(str(db_path))
        macro = gather_macro_data(str(db_path))
        context = build_shared_context(str(db_path))

        if "VIX:" not in tactical or "Macro indicators:" not in macro or "VIX:" not in context:
            return (
                False,
                "council data gatherers did not surface repo-native VIX/macro data from current schemas",
            )

        return True, "council data gatherers read repo-native schema successfully"
    finally:
        _cleanup_temp_path(db_path)


def _watch_notification_contract_probe() -> tuple[bool, str]:
    source = (ROOT / "src" / "scheduler" / "watch.py").read_text(encoding="utf-8")
    bad_refs = [
        ref
        for ref in ["ps.entry_price", "ps.stop_level", "ps.target_1", "ps.shares"]
        if ref in source
    ]
    if bad_refs:
        return False, f"watch loop still references nonexistent PositionSizing fields: {', '.join(bad_refs)}"

    return True, "watch loop notification path does not reference removed PositionSizing fields"


def _pytest_task(*args: str) -> Callable[[], tuple[bool, str]]:
    def _runner() -> tuple[bool, str]:
        return _run_subprocess([sys.executable, "-m", "pytest", *args])

    return _runner


def _secret_scan_probe() -> tuple[bool, str]:
    patterns = [
        re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
        re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    ]

    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if tracked.returncode != 0:
        return False, f"git ls-files failed: {tracked.stderr.strip()}"

    hits: list[str] = []
    skip_prefixes = (".venv/", "frontend/node_modules/")
    for rel in tracked.stdout.splitlines():
        if not rel or rel.startswith(skip_prefixes):
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                hits.append(f"{rel}: {match.group(0)[:16]}...")
                break

    if hits:
        return False, "possible committed secrets detected:\n" + "\n".join(hits[:20])

    return True, "no obvious committed credential prefixes found in tracked files"


TASKS: list[TaskSpec] = [
    TaskSpec(
        task_id="validator_real_packet_probe",
        title="Validator accepts a real TradePacket",
        command="probe: validator_real_packet_probe",
        runner=_validator_real_packet_probe,
    ),
    TaskSpec(
        task_id="live_guard_fail_closed_probe",
        title="Live trading fails closed on state-query errors",
        command="probe: live_guard_fail_closed_probe",
        runner=_live_guard_fail_closed_probe,
    ),
    TaskSpec(
        task_id="live_close_broker_truth_probe",
        title="Live exit preserves broker truth when exit submission fails",
        command="probe: live_close_broker_truth_probe",
        runner=_live_close_broker_truth_probe,
    ),
    TaskSpec(
        task_id="local_shadow_close_live_guard_probe",
        title="Local shadow close route blocks live trades",
        command="probe: local_shadow_close_live_guard_probe",
        runner=_local_shadow_close_live_guard_probe,
    ),
    TaskSpec(
        task_id="paper_entry_requires_broker_probe",
        title="Paper entry requires broker submission",
        command="probe: paper_entry_requires_broker_probe",
        runner=_paper_entry_requires_broker_probe,
    ),
    TaskSpec(
        task_id="council_schema_probe",
        title="Council readers match repo-native DB schemas",
        command="probe: council_schema_probe",
        runner=_council_schema_probe,
    ),
    TaskSpec(
        task_id="watch_notification_contract_probe",
        title="Watch-loop trade-open notification matches PositionSizing contract",
        command="probe: watch_notification_contract_probe",
        runner=_watch_notification_contract_probe,
    ),
    TaskSpec(
        task_id="live_validator_pytest_suite",
        title="Live trading and validator regression suite",
        command=f"{sys.executable} -m pytest tests/test_live_trading.py tests/test_llm_validator.py tests/test_llm_client.py -q",
        runner=_pytest_task(
            "tests/test_live_trading.py",
            "tests/test_llm_validator.py",
            "tests/test_llm_client.py",
            "-q",
        ),
    ),
    TaskSpec(
        task_id="local_api_routes_suite",
        title="Local API route regression suite",
        command=f"{sys.executable} -m pytest tests/test_local_api_routes.py -q",
        runner=_pytest_task("tests/test_local_api_routes.py", "-q"),
    ),
    TaskSpec(
        task_id="risk_governor_tests",
        title="Risk governor regression suite",
        command=f"{sys.executable} -m pytest tests/test_risk_governor.py -q",
        runner=_pytest_task("tests/test_risk_governor.py", "-q"),
    ),
    TaskSpec(
        task_id="council_agents_contracts",
        title="Council agent contract suite",
        command=f"{sys.executable} -m pytest tests/test_council_agents.py -q",
        runner=_pytest_task("tests/test_council_agents.py", "-q"),
    ),
    TaskSpec(
        task_id="council_protocol_contracts",
        title="Council protocol/session contract suite",
        command=f"{sys.executable} -m pytest tests/test_council.py -q",
        runner=_pytest_task("tests/test_council.py", "-q"),
    ),
    TaskSpec(
        task_id="features_fixture_tests",
        title="Feature-engine fixture stability suite",
        command=f"{sys.executable} -m pytest tests/test_features.py -q",
        runner=_pytest_task("tests/test_features.py", "-q"),
    ),
    TaskSpec(
        task_id="main_refactor_tests",
        title="Main CLI guardrail suite",
        command=f"{sys.executable} -m pytest tests/test_main_refactor.py -q",
        runner=_pytest_task("tests/test_main_refactor.py", "-q"),
    ),
    TaskSpec(
        task_id="secret_scan",
        title="Committed secret prefix scan",
        command="probe: secret_scan",
        runner=_secret_scan_probe,
    ),
]


def _load_baseline(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    expected = {}
    for row in data.get("expected_failures", []):
        expected[row["task_id"]] = row
    return expected


def _classify(task_id: str, passed: bool, expected: dict) -> str:
    if passed and task_id in expected:
        return "improvement"
    if not passed and task_id in expected:
        return "baseline_fail"
    if passed:
        return "pass"
    return "unexpected_fail"


def _status_emoji(status: str) -> str:
    return {
        "green": "GREEN",
        "yellow": "YELLOW",
        "red": "RED",
    }.get(status, status.upper())


def _task_emoji(classification: str) -> str:
    return {
        "pass": "PASS",
        "baseline_fail": "BASELINE",
        "improvement": "IMPROVED",
        "unexpected_fail": "REGRESSION",
    }[classification]


def _build_report(summary: dict) -> str:
    lines = [
        f"# Daily Repo Audit — {summary['date_utc']}",
        "",
        f"Overall status: **{summary['overall_status'].upper()}**",
        f"Generated at: `{summary['generated_at_utc']}`",
    ]

    if summary.get("run_url"):
        lines.append(f"Run URL: {summary['run_url']}")

    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- Passed: {summary['counts']['pass']}",
            f"- Baseline failures: {summary['counts']['baseline_fail']}",
            f"- Improvements: {summary['counts']['improvement']}",
            f"- Unexpected failures: {summary['counts']['unexpected_fail']}",
            "",
            "Issue policy:",
            "Known failures stay linked to the existing audit issues from 2026-03-29.",
            "Unexpected failures are eligible for automatic GitHub issue creation or reopening.",
            "",
            "## Tasks",
            "",
            "| Task | Result | Linked Issue | Duration |",
            "| --- | --- | --- | --- |",
        ]
    )

    for result in summary["tasks"]:
        issue = result.get("issue_number")
        issue_cell = f"#{issue}" if issue else "-"
        lines.append(
            f"| `{result['task_id']}` | {result['classification']} | {issue_cell} | {result['duration_seconds']:.2f}s |"
        )

    lines.extend(["", "## Details", ""])
    for result in summary["tasks"]:
        lines.extend(
            [
                f"### {result['title']}",
                "",
                f"- Task ID: `{result['task_id']}`",
                f"- Result: `{result['classification']}`",
                f"- Command: `{result['command']}`",
                f"- Duration: `{result['duration_seconds']:.2f}s`",
            ]
        )
        if result.get("issue_number"):
            lines.append(f"- Linked issue: `#{result['issue_number']}`")
        if result.get("baseline_reason"):
            lines.append(f"- Baseline note: {result['baseline_reason']}")
        lines.append("")
        lines.append(result["summary"])
        lines.append("")
        if result.get("output_excerpt"):
            lines.extend(
                [
                    "```text",
                    result["output_excerpt"],
                    "```",
                    "",
                ]
            )

    return "\n".join(lines).strip() + "\n"


def _build_step_summary(summary: dict) -> str:
    lines = [
        f"## Daily Repo Audit: {_status_emoji(summary['overall_status'])}",
        "",
        f"- Date (UTC): `{summary['date_utc']}`",
        f"- Passed: {summary['counts']['pass']}",
        f"- Baseline failures: {summary['counts']['baseline_fail']}",
        f"- Improvements: {summary['counts']['improvement']}",
        f"- Unexpected failures: {summary['counts']['unexpected_fail']}",
        "",
        "| Task | Result |",
        "| --- | --- |",
    ]

    for result in summary["tasks"]:
        lines.append(
            f"| `{result['task_id']}` | {_task_emoji(result['classification'])} |"
        )

    if summary["counts"]["unexpected_fail"]:
        lines.extend(["", "Unexpected failures trigger GitHub issue sync in the workflow."])

    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the daily repo audit")
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "audit-output"),
        help="Directory for markdown/json outputs",
    )
    parser.add_argument(
        "--baseline",
        default=str(DEFAULT_BASELINE_PATH),
        help="Path to baseline JSON",
    )
    parser.add_argument(
        "--run-url",
        default="",
        help="Optional GitHub Actions run URL",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline = _load_baseline(Path(args.baseline))

    now = _utc_now()
    date_utc = now.strftime("%Y-%m-%d")

    results = []
    for task in TASKS:
        started = time.perf_counter()
        try:
            passed, output = task.runner()
        except Exception as exc:  # pragma: no cover - catastrophic path
            passed = False
            output = f"{type(exc).__name__}: {exc}"
        duration = time.perf_counter() - started

        classification = _classify(task.task_id, passed, baseline)
        baseline_entry = baseline.get(task.task_id, {})
        excerpt = _tail(output)
        results.append(
            {
                "task_id": task.task_id,
                "title": task.title,
                "command": task.command,
                "classification": classification,
                "duration_seconds": round(duration, 3),
                "summary": output.splitlines()[0] if output else "No output",
                "output_excerpt": excerpt,
                "issue_number": baseline_entry.get("issue_number"),
                "baseline_reason": baseline_entry.get("reason"),
            }
        )

    counts = {
        "pass": sum(1 for row in results if row["classification"] == "pass"),
        "baseline_fail": sum(
            1 for row in results if row["classification"] == "baseline_fail"
        ),
        "improvement": sum(
            1 for row in results if row["classification"] == "improvement"
        ),
        "unexpected_fail": sum(
            1 for row in results if row["classification"] == "unexpected_fail"
        ),
    }

    if counts["unexpected_fail"] > 0:
        overall_status = "red"
    elif counts["baseline_fail"] > 0 or counts["improvement"] > 0:
        overall_status = "yellow"
    else:
        overall_status = "green"

    summary = {
        "generated_at_utc": now.isoformat(),
        "date_utc": date_utc,
        "overall_status": overall_status,
        "run_url": args.run_url,
        "counts": counts,
        "tasks": results,
        "unexpected_failures": [
            row for row in results if row["classification"] == "unexpected_fail"
        ],
        "improvements": [
            row for row in results if row["classification"] == "improvement"
        ],
        "baseline_failures": [
            row for row in results if row["classification"] == "baseline_fail"
        ],
    }

    report_text = _build_report(summary)
    step_summary = _build_step_summary(summary)

    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (output_dir / "latest-summary.md").write_text(step_summary, encoding="utf-8")
    (output_dir / f"daily-repo-audit-{date_utc}.md").write_text(
        report_text, encoding="utf-8"
    )

    print(step_summary.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
