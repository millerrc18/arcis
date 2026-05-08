"""Daily and weekly auditor agent for risk monitoring.

Called by: scheduler.watch
Calls: config, email.notifier, evaluation.cto_report, risk.governor, training.claude_client, training.versioning
Owns tables: none
Config keys: none
Tests: tests/test_auditor.py

Analyzes trading activity and identifies strategy drift, concentration risk,
execution quality issues, model behavior problems, and regime awareness gaps.
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import DB_PATH, load_config
from src.utils.db import connect_db
from src.training.versioning import init_training_tables
from src.shadow_trading.exit_reason import outcome_stats_filter_sql

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# Flag categories that must NEVER be downgraded from CRITICAL during
# bootcamp mode. These signal loss-of-containment, not model uncertainty —
# a compromised safety net always warrants a halt regardless of sample size.
_NEVER_DOWNGRADE = frozenset({
    "risk_governor_breach",
    "emergency_halt_bypass",
})

AUDITOR_SYSTEM_PROMPT = """You are a risk management auditor for an autonomous equity trading system. Your job is to review the day's trading activity and identify any patterns, anomalies, or risks that need human attention.

You will receive a structured JSON report of today's trading activity. Analyze it and produce a brief, actionable assessment.

Focus on:
1. STRATEGY DRIFT: Are trades consistent with the pullback-in-trend strategy, or is the system drifting?
2. CONCENTRATION RISK: Is the portfolio becoming over-concentrated in any sector or correlated positions?
3. EXECUTION QUALITY: Are entries, stops, and exits behaving as designed? Any signs of slippage or bad fills?
4. MODEL BEHAVIOR: Is the model showing signs of overconfidence (high conviction on trades that lose)? Is confidence calibrated?
5. REGIME AWARENESS: Is the system adapting appropriately to the current market regime, or is it forcing trades in hostile conditions?
6. ANOMALIES: Anything unusual — a trade that doesn't match the stated criteria, a sudden change in behavior, unexpected losses.

OUTPUT FORMAT (JSON):

{
    "overall_assessment": "green" or "yellow" or "red",
    "summary": "One paragraph overall assessment",
    "flags": [
        {
            "severity": "warning" or "alert" or "critical",
            "category": "concentration" or "drift" or "execution" or "model" or "regime" or "anomaly",
            "description": "Specific description of the concern",
            "recommendation": "Specific action to take"
        }
    ],
    "metrics_to_watch": ["list of metrics that are trending in concerning directions"],
    "model_health": "healthy" or "degrading" or "overconfident" or "under-confident"
}"""

WEEKLY_AUDITOR_PROMPT = """You are a risk management auditor conducting a WEEKLY deep review of an autonomous equity trading system. Unlike the daily audit, you are looking for TRENDS and slow-burning problems.

You will receive:
1. A structured performance report for the full week
2. Daily audit summaries from each day
3. Model version and confidence calibration data

Focus on:
1. Performance trends — is the system getting better or worse?
2. Model degradation — are daily audit flags getting more frequent or severe?
3. Confidence calibration — does the model's self-assessed conviction predict outcomes?
4. Sector drift — is the portfolio gradually concentrating?
5. Regime adaptation — is the system correctly reducing activity in hostile regimes?

OUTPUT FORMAT (JSON):

{
    "overall_assessment": "green" or "yellow" or "red",
    "summary": "One paragraph trend assessment",
    "flags": [
        {
            "severity": "warning" or "alert" or "critical",
            "category": "trend" or "model" or "calibration" or "concentration" or "regime",
            "description": "Specific trend description",
            "recommendation": "Specific corrective action"
        }
    ],
    "metrics_to_watch": ["list of metrics trending badly"],
    "model_health": "healthy" or "degrading" or "overconfident" or "under-confident"
}"""


def run_daily_audit(db_path: str = DB_PATH) -> dict:
    """Run the daily auditor agent on today's trading activity.

    Generates the CTO report for today, sends it to Claude for analysis,
    and produces a structured audit result.
    """
    from src.evaluation.cto_report import generate_cto_report
    from src.training.claude_client import generate_training_example

    init_training_tables(db_path)

    # Generate data for audit
    cto_data = generate_cto_report(days=1, db_path=db_path)

    # Add portfolio state
    try:
        from src.risk.governor import get_portfolio_state
        portfolio = get_portfolio_state(db_path)
        cto_data["portfolio_state"] = portfolio
    except Exception:
        pass

    # Send to Claude for analysis
    audit_input = json.dumps(cto_data, indent=2, default=str)
    response = generate_training_example(AUDITOR_SYSTEM_PROMPT, audit_input, purpose="audit")

    if not response:
        # Return a minimal green audit if Claude is unavailable
        result = {
            "overall_assessment": "green",
            "summary": "Audit unavailable — Claude API not reachable.",
            "flags": [],
            "metrics_to_watch": [],
            "model_health": "unknown",
        }
    else:
        # Parse JSON from response
        try:
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                result = json.loads(json_match.group())
            else:
                result = {"overall_assessment": "yellow", "summary": response[:500],
                          "flags": [], "metrics_to_watch": [], "model_health": "unknown"}
        except (json.JSONDecodeError, AttributeError):
            result = {"overall_assessment": "yellow", "summary": response[:500],
                      "flags": [], "metrics_to_watch": [], "model_health": "unknown"}

    # Store result
    audit_id = str(uuid.uuid4())
    now = datetime.now(ET)
    created_at = now.isoformat()
    audit_date = now.strftime("%Y-%m-%d")

    with connect_db(db_path) as conn:
        conn.execute(
            """INSERT INTO audit_reports
               (audit_id, created_at, audit_date, overall_assessment, summary,
                flags, metrics_to_watch, model_health, full_report)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (audit_id, created_at, audit_date,
             result.get("overall_assessment", "green"),
             result.get("summary", ""),
             json.dumps(result.get("flags", [])),
             json.dumps(result.get("metrics_to_watch", [])),
             result.get("model_health", "unknown"),
             json.dumps(result)),
        )
        conn.commit()

    logger.info("[AUDIT] Daily assessment: %s — %s",
                result.get("overall_assessment"), (result.get("summary") or "")[:100])
    return result


def run_weekly_audit(days: int = 7, db_path: str = DB_PATH) -> dict:
    """Run a deeper weekly audit that looks at trends."""
    from src.evaluation.cto_report import generate_cto_report
    from src.training.claude_client import generate_training_example

    init_training_tables(db_path)

    # Get weekly CTO report
    cto_data = generate_cto_report(days=days, db_path=db_path)

    # Get daily audits from the week
    cutoff = (datetime.now(ET) - timedelta(days=days)).isoformat()
    with connect_db(db_path) as conn:
        conn.row_factory = sqlite3.Row
        daily_audits = conn.execute(
            "SELECT audit_date, overall_assessment, summary, flags FROM audit_reports "
            "WHERE created_at >= ? ORDER BY created_at",
            (cutoff,),
        ).fetchall()

    daily_summaries = []
    for a in daily_audits:
        d = dict(a)
        if d.get("flags"):
            try:
                d["flags"] = json.loads(d["flags"])
            except (json.JSONDecodeError, TypeError):
                pass
        daily_summaries.append(d)

    audit_input = json.dumps({
        "weekly_report": cto_data,
        "daily_audits": daily_summaries,
    }, indent=2, default=str)

    response = generate_training_example(WEEKLY_AUDITOR_PROMPT, audit_input, purpose="audit")

    if not response:
        return {"overall_assessment": "green", "summary": "Weekly audit unavailable.",
                "flags": [], "metrics_to_watch": [], "model_health": "unknown"}

    try:
        import re
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            result = json.loads(json_match.group())
        else:
            result = {"overall_assessment": "yellow", "summary": response[:500],
                      "flags": [], "metrics_to_watch": [], "model_health": "unknown"}
    except (json.JSONDecodeError, AttributeError):
        result = {"overall_assessment": "yellow", "summary": response[:500],
                  "flags": [], "metrics_to_watch": [], "model_health": "unknown"}

    # Store as audit report
    audit_id = str(uuid.uuid4())
    now = datetime.now(ET)
    with connect_db(db_path) as conn:
        conn.execute(
            """INSERT INTO audit_reports
               (audit_id, created_at, audit_date, overall_assessment, summary,
                flags, metrics_to_watch, model_health, full_report)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (audit_id, now.isoformat(), now.strftime("%Y-%m-%d"),
             result.get("overall_assessment", "green"),
             result.get("summary", ""),
             json.dumps(result.get("flags", [])),
             json.dumps(result.get("metrics_to_watch", [])),
             result.get("model_health", "unknown"),
             json.dumps(result)),
        )
        conn.commit()

    return result


def check_escalation(audit: dict, db_path: str = DB_PATH) -> list[dict]:
    """Check if any audit flags require immediate escalation.

    Escalation actions:
    - "critical" severity → halt trading immediately + send alert email
    - "alert" severity → send alert email, continue trading
    - "warning" severity → log only, include in next scheduled email

    During bootcamp (< 50 closed trades), critical flags are downgraded to alerts
    and auto-halt is skipped. The system needs to accumulate trades to prove edge.
    """
    actions = []
    flags = audit.get("flags", [])

    # Check if we're in bootcamp mode (< 50 closed trades).
    #
    # Post-bootcamp graduation override: `live_trading.post_bootcamp` config key
    # (default False) makes graduation STICKY. Once the operator declares
    # Stage 1 baseline signed and sets `post_bootcamp: true` in
    # settings.local.yaml, bootcamp_mode never auto-flips back — even when
    # closed_count drops below 50 (e.g., when reconciled_stale rows are
    # filtered out per Wave 4 H5, dropping the honest count from 50 to 6).
    # Without this override, H5's data-integrity filter would silently
    # regress the system into bootcamp critical-alert downgrade behavior.
    # Default False keeps fresh installs in bootcamp until manually graduated.
    bootcamp_mode = False
    closed_count = 0
    post_bootcamp = False
    try:
        cfg = load_config()
        post_bootcamp = bool(cfg.get("live_trading", {}).get("post_bootcamp", False))
    except Exception:
        pass
    try:
        with connect_db(db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed'"
                f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
            ).fetchone()
            closed_count = row[0] if row else 0
            bootcamp_mode = (not post_bootcamp) and (closed_count < 50)
    except Exception:
        pass

    for flag in flags:
        severity = flag.get("severity", "warning")
        category = flag.get("category", "")

        if severity == "critical":
            # Operator policy 2026-05-08: kill switch is operator-action-only.
            # The auditor NEVER auto-halts. CRITICAL flags escalate via email +
            # logger.critical so the operator can decide whether to halt manually.
            # Bootcamp-mode downgrade still applies for model-quality CRITICALs
            # (miscalibration etc.) so they don't spam alerts during the early
            # 50-trade learning window — _NEVER_DOWNGRADE categories (loss-of-
            # containment signals) keep critical severity in their alert.
            if bootcamp_mode and category not in _NEVER_DOWNGRADE:
                logger.warning(
                    "[AUDIT] CRITICAL flag DOWNGRADED to alert (bootcamp mode, %d closed trades): %s",
                    closed_count, flag.get("description"),
                )
                severity = "alert"
                flag["severity"] = "alert"
                flag["description"] = f"[BOOTCAMP DOWNGRADE] {flag.get('description', '')}"
            else:
                # Production mode — alert operator, no auto-halt
                logger.critical(
                    "[AUDIT] CRITICAL flag — operator action required (auto-halt disabled per policy): %s",
                    flag.get("description"),
                )

                actions.append({
                    "action": "operator_action_required",
                    "severity": "critical",
                    "flag": flag,
                })

                # Send alert email — operator decides whether to halt
                try:
                    from src.email.notifier import send_email
                    subject = "[TRADE DESK] CRITICAL AUDIT FLAG — Operator Action Required"
                    body = (
                        f"CRITICAL AUDIT FLAG\n\n"
                        f"Category: {flag.get('category')}\n"
                        f"Description: {flag.get('description')}\n"
                        f"Recommendation: {flag.get('recommendation')}\n\n"
                        f"Trading was NOT auto-halted (operator-only kill-switch policy 2026-05-08). "
                        f"Review and halt manually if appropriate via:\n"
                        f"  - CLI: python -m src.main halt-trading\n"
                        f"  - Dashboard halt button\n"
                        f"  - API: POST /api/system/halt-trading"
                    )
                    send_email(subject, body)
                except Exception as e:
                    logger.error("[AUDIT] Failed to send critical alert email: %s", e)

                actions.append({"action": "email_alert", "severity": "critical", "flag": flag})

        elif severity == "alert":
            try:
                from src.email.notifier import send_email
                subject = "[TRADE DESK] AUDIT ALERT"
                body = (
                    f"AUDIT ALERT\n\n"
                    f"Category: {flag.get('category')}\n"
                    f"Description: {flag.get('description')}\n"
                    f"Recommendation: {flag.get('recommendation')}"
                )
                send_email(subject, body)
            except Exception as e:
                logger.error("[AUDIT] Failed to send alert email: %s", e)

            actions.append({"action": "email_alert", "severity": "alert", "flag": flag})

        else:
            actions.append({"action": "log_only", "severity": "warning", "flag": flag})

    return actions
