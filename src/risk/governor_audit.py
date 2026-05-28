"""Governor audit gate — deterministic-audit-driven entry suppression.

Called by: risk.governor
Calls: config, utils.db
Owns tables: none
Config keys: none
Tests: tests/test_auditor.py, tests/test_risk_governor.py

Extracted from ``src/risk/governor.py`` (Phase 5 PR-C T14). This module
holds the governor's deterministic-audit gate: when the most recent daily
audit report carries an unexpired ``critical`` deterministic-precheck flag,
new entries are suppressed while exit management and reconciliation keep
running. It does NOT write the global halt file — entry risk is throttled,
not the whole trading loop.

The single public function ``audit_entry_suppression_reason`` is called by
``RiskGovernor.check_trade`` (re-exported from ``governor`` for backward
compatibility) as Check 0c (``deterministic_audit``).
"""

import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.utils.db import connect_db

# All risk timestamps use Eastern Time because US equity markets
# operate on ET and daily loss limits reset at midnight ET.
_ET = ZoneInfo("America/New_York")

logger = logging.getLogger(__name__)

_AUDIT_ENTRY_SUPPRESSION_LOOKBACK_HOURS = 36


def audit_entry_suppression_reason(db_path: str = DB_PATH) -> str | None:
    """Return a reason to block new entries when deterministic audit is critical.

    This does not write the global halt file. Entry risk is suppressed while
    exit management and reconciliation continue to run.
    """
    try:
        with connect_db(db_path) as conn:
            row = conn.execute(
                "SELECT created_at, overall_assessment, full_report "
                "FROM audit_reports ORDER BY created_at DESC LIMIT 1",
            ).fetchone()
    except Exception as exc:
        logger.debug("[RISK] Audit entry suppression check failed: %s", exc)
        return None

    if not row:
        return None

    try:
        created_dt = datetime.fromisoformat(str(row[0]))
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=_ET)
        if datetime.now(_ET) - created_dt > timedelta(hours=_AUDIT_ENTRY_SUPPRESSION_LOOKBACK_HOURS):
            return None
    except (TypeError, ValueError):
        return None

    try:
        report = json.loads(row[2] or "{}")
    except (TypeError, json.JSONDecodeError):
        return None

    deterministic = report.get("deterministic_prechecks") or [
        flag for flag in report.get("flags", [])
        if flag.get("source") == "deterministic_precheck"
    ]
    critical = [
        flag for flag in deterministic
        if flag.get("severity") == "critical"
    ]
    if not critical:
        return None

    description = critical[0].get("description") or "entry risk suppressed"
    return f"Latest deterministic audit is critical: {description}"
