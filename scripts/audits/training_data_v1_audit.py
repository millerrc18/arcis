"""Training Data v1-Citation Audit — CLI entry point.

Runs the three-pass audit (A: v1-citation contamination, B: XML +
label format drift, C: TF-IDF leakage probe) against the
`training_examples` table. Quarantines rows in place via UPDATE
(never DELETE); leaves `quarantined=0` on all other rows.

Usage:
    python scripts/audits/training_data_v1_audit.py
    python scripts/audits/training_data_v1_audit.py --dry-run
    python scripts/audits/training_data_v1_audit.py --pass A --pass B
    python scripts/audits/training_data_v1_audit.py --output report.md

Called by: operator (CLI), src.commands.diagnostic_handlers (dashboard)
Calls: src.training.audit.core
Owns tables: training_examples (when --dry-run is not set)
Config keys: none
Tests: tests/audits/test_training_audit_cli.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure repo root is on sys.path when invoked directly.
repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root))

from src.training.audit.core import run_audit  # noqa: E402
from src.config import DB_PATH  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI args.

    Exposed as a module function so the e2e test can drive it directly.
    """
    ap = argparse.ArgumentParser(
        description="Training Data v1-Citation Audit (three-pass quarantine)",
    )
    ap.add_argument("--db", default=str(DB_PATH), help="SQLite path")
    ap.add_argument(
        "--output",
        default="docs/audits/training-audit.md",
        help="Markdown report output path",
    )
    ap.add_argument(
        "--plot-dir",
        default="docs/audits/training-audit-plots/",
        help="Plot output dir (unused in v1; kept for dashboard_runner)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write quarantine flags; just report.",
    )
    ap.add_argument(
        "--pass",
        dest="passes",
        action="append",
        choices=["A", "B", "C"],
        help="Run only the specified pass(es); repeatable.",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the audit; return 0 on success, non-zero on failure."""
    args = parse_args(argv)
    summary = run_audit(
        db_path=args.db,
        dry_run=args.dry_run,
        passes=args.passes,
        report_path=args.output,
        plot_dir=args.plot_dir,
    )
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
