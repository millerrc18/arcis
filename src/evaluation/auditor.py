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

from src.config import load_config
from src.training.versioning import init_training_tables

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

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


def run_daily_audit(db_path: str = "ai_research_desk.sqlite3") -> dict:
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

    with sqlite3.connect(db_path) as conn:
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


def run_weekly_audit(days: int = 7, db_path: str = "ai_research_desk.sqlite3") -> dict:
    """Run a deeper weekly audit that looks at trends."""
    from src.evaluation.cto_report import generate_cto_report
    from src.training.claude_client import generate_training_example

    init_training_tables(db_path)

    # Get weekly CTO report
    cto_data = generate_cto_report(days=days, db_path=db_path)

    # Get daily audits from the week
    cutoff = (datetime.now(ET) - timedelta(days=days)).isoformat()
    with sqlite3.connect(db_path) as conn:
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
    with sqlite3.connect(db_path) as conn:
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


def check_escalation(audit: dict, db_path: str = "ai_research_desk.sqlite3") -> list[dict]:
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

    # Check if we're in bootcamp mode (< 50 closed trades)
    bootcamp_mode = False
    try:
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed'").fetchone()
            closed_count = row[0] if row else 0
            bootcamp_mode = closed_count < 50
    except Exception:
        pass

    for flag in flags:
        severity = flag.get("severity", "warning")

        if severity == "critical":
            if bootcamp_mode:
                # During bootcamp, downgrade critical to alert — don't halt
                logger.warning(
                    "[AUDIT] CRITICAL flag DOWNGRADED to alert (bootcamp mode, %d closed trades): %s",
                    closed_count, flag.get("description"),
                )
                severity = "alert"
                flag["severity"] = "alert"
                flag["description"] = f"[BOOTCAMP DOWNGRADE] {flag.get('description', '')}"
            else:
                # Production mode — halt trading
                from src.risk.governor import _global_halt
                _global_halt(True)
                logger.critical("[AUDIT] CRITICAL flag — trading halted: %s", flag.get("description"))

                actions.append({
                    "action": "halt_trading",
                    "severity": "critical",
                    "flag": flag,
                })

                # Send alert email
                try:
                    from src.email.notifier import send_email
                    subject = "[TRADE DESK] CRITICAL AUDIT ALERT — Trading Halted"
                    body = (
                        f"CRITICAL AUDIT FLAG\n\n"
                        f"Category: {flag.get('category')}\n"
                        f"Description: {flag.get('description')}\n"
                        f"Recommendation: {flag.get('recommendation')}\n\n"
                        f"Trading has been automatically halted. Resume via dashboard or CLI."
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
