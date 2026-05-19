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

_LLM_AUDIT_MIN_SAMPLE = 10
"""Minimum closed-trade count below which the LLM-narrative audit is suppressed.

Rationale (W21, v0.36.27): the LLM auditor was generating CRITICAL-system-
malfunction Telegrams on small samples:

  - 2026-05-18 (N=2 trades attributed to arcis:v1.0.0 model version):
    "0% win rate vs 57% for base model, negative expectancy"
    Real picture across the full 10-trade window: 4 wins / 6 losses (40%).

  - 2026-05-19 (N=3 closes, all with recommendation_id=None):
    "100% of trades executed with scores below 70, all resulting in
    immediate stop losses, indicating complete failure of the scoring/
    selection..." Real picture: 2 stop-outs + 1 stale-reconcile cleanup,
    net P&L +$24.59. The 3 trades all defaulted to score=0 in the band
    logic because they were pullback-strategy trades with broken
    recommendation_id linkage (a real bug, but not 'system malfunction').

Below this threshold, the LLM call is skipped and replaced with a
deterministic low-volume summary. Deterministic precheck flags
(`_append_deterministic_prechecks`) still run — they have their own
per-check sample guards from v0.36.22 (drawdown ceiling, etc.). This way
the deterministic surface stays sharp while the LLM commentary stops
manufacturing false alarms on tiny samples.

10 is a conservative floor: catches the worst small-sample cases (N≤3)
that motivated this fix while still allowing the LLM to speak on normal
trading days (typically 5-20 closes for SP100 swing strategy). The
follow-up to handle per-model-subgroup small samples (which is what
yesterday's audit tripped on) is queued for post-freeze."""

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

    # v0.36.27: small-sample guard. Skip LLM narrative when trades_closed
    # falls below _LLM_AUDIT_MIN_SAMPLE — the LLM is unreliable on tiny
    # samples and was generating CRITICAL Telegrams on N=2 and N=3. The
    # deterministic prechecks below still run (they have their own
    # per-check sample guards from v0.36.22).
    trade_summary = cto_data.get("trade_summary") or {}
    try:
        trades_closed = int(trade_summary.get("trades_closed") or 0)
    except (TypeError, ValueError):
        trades_closed = 0

    if trades_closed < _LLM_AUDIT_MIN_SAMPLE:
        result = {
            "overall_assessment": "green",
            "summary": (
                f"Low-volume day ({trades_closed} closes, threshold "
                f"{_LLM_AUDIT_MIN_SAMPLE}). LLM narrative suppressed to avoid "
                "small-sample extrapolation. Deterministic checks below."
            ),
            "flags": [],
            "metrics_to_watch": [],
            "model_health": "unknown",
        }
    else:
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

    _append_deterministic_prechecks(result, cto_data, db_path)

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


def _append_deterministic_prechecks(result: dict, cto_data: dict, db_path: str) -> None:
    """Append hard-coded data-quality/risk checks to the LLM audit result.

    Claude can miss mechanical failure modes in sparse reports. These prechecks
    are deterministic and therefore run even when the Claude audit is green or
    unavailable.
    """
    flags = _collect_deterministic_precheck_flags(db_path, cto_data)
    result["deterministic_prechecks"] = flags
    if not flags:
        return

    result.setdefault("flags", [])
    result["flags"].extend(flags)

    metrics = result.setdefault("metrics_to_watch", [])
    for metric in (
        "unknown_exit_reason_ratio",
        "missing_bracket_coverage",
        "reconciled_stale_closures",
        "max_drawdown_pct",
        "model_win_rate",
    ):
        if metric not in metrics:
            metrics.append(metric)

    if any(flag.get("severity") == "critical" for flag in flags):
        result["overall_assessment"] = "red"
        if result.get("model_health") in (None, "", "healthy", "unknown"):
            result["model_health"] = "degrading"
    elif result.get("overall_assessment") == "green":
        result["overall_assessment"] = "yellow"


def _collect_deterministic_precheck_flags(db_path: str, cto_data: dict) -> list[dict]:
    """Return deterministic audit flags for failure modes the watch loop can prove."""
    flags: list[dict] = []
    _check_unknown_exit_ratio(flags, db_path)
    _check_bracket_coverage(flags, db_path)
    _check_reconciled_stale_volume(flags, db_path)
    _check_drawdown(flags, cto_data)
    _check_model_win_rate(flags, cto_data)
    _check_regime_classification_flag(flags, db_path)
    return flags


def _check_regime_classification_flag(flags: list[dict], db_path: str) -> None:
    """Wire `_check_regime_classification` into the deterministic precheck flag stream.

    v0.36.13 (QA Cycle 2 wire-up): the Track-(d) audit-hardening commit added
    `_check_regime_classification(db_path)` as a stats helper that excludes
    NULL `regime_at_entry` from the denominator (instead of folding NULL into
    'unknown'). The helper itself returns observability stats but DOES NOT
    emit a flag. Without this caller, the 'All trades classified as unknown
    regime' false-positive in the daily Telegram audit alerts would continue
    firing because nothing in the deterministic precheck path was invoking
    the corrected denominator math.

    Fires CRITICAL when more than 50% of measurable closed trades have
    `regime_at_entry='unknown'` over a denominator of at least 5 trades.
    """
    stats = _check_regime_classification(db_path)
    denominator = stats.get("denominator", 0)
    if denominator < 5:
        # Not enough measurable trades to assess; remain silent rather than
        # alarm operators on a thin denominator.
        return
    unknown_fraction = stats.get("unknown_fraction", 0.0)
    if unknown_fraction <= 0.5:
        return
    flags.append(_deterministic_flag(
        severity="critical",
        category="regime",
        description=(
            f"{unknown_fraction * 100:.1f}% of {denominator} measurable closed "
            f"trades have regime_at_entry='unknown' (NULL entries excluded "
            f"from denominator; null_count={stats.get('null_count', 0)})"
        ),
        recommendation=(
            "Investigate regime classification system. Pre-fix audit folded "
            "NULL into 'unknown' which inflated the denominator and fired "
            "false-positive alerts; this flag fires only on REAL unknown-class "
            "saturation among measurable trades."
        ),
        metric="regime_unknown_fraction",
        value=stats,
        threshold="<=50%",
    ))


def _deterministic_flag(
    *,
    severity: str,
    category: str,
    description: str,
    recommendation: str,
    metric: str,
    value,
    threshold,
) -> dict:
    return {
        "severity": severity,
        "category": category,
        "description": description,
        "recommendation": recommendation,
        "source": "deterministic_precheck",
        "metric": metric,
        "value": value,
        "threshold": threshold,
    }


def _check_unknown_exit_ratio(flags: list[dict], db_path: str) -> None:
    cutoff = (datetime.now(ET) - timedelta(days=30)).isoformat()
    try:
        with connect_db(db_path) as conn:
            row = conn.execute(
                "SELECT "
                "COUNT(*) as total, "
                "SUM(CASE WHEN exit_reason IS NULL OR exit_reason = '' "
                "OR LOWER(exit_reason) = 'unknown' THEN 1 ELSE 0 END) as unknown_count "
                "FROM shadow_trades "
                "WHERE status = 'closed' "
                "AND COALESCE(quarantined, 0) = 0 "
                "AND COALESCE(actual_exit_time, updated_at, created_at) >= ?",
                (cutoff,),
            ).fetchone()
    except Exception as exc:
        logger.warning("[AUDIT] Unknown-exit precheck failed: %s", exc)
        return

    total = int((row[0] if row else 0) or 0)
    unknown_count = int((row[1] if row else 0) or 0)
    if total < 10 or unknown_count == 0:
        return

    ratio = unknown_count / total
    if ratio >= 0.25:
        flags.append(_deterministic_flag(
            severity="critical",
            category="data_integrity",
            description=(
                f"Unknown exit reasons are {ratio:.0%} of recent closed trades "
                f"({unknown_count}/{total})."
            ),
            recommendation=(
                "Repair only rows with provable broker/order evidence; leave ambiguous rows "
                "as manual-review data-quality debt."
            ),
            metric="unknown_exit_reason_ratio",
            value=round(ratio, 4),
            threshold=0.25,
        ))
    elif ratio >= 0.10:
        flags.append(_deterministic_flag(
            severity="alert",
            category="data_integrity",
            description=(
                f"Unknown exit reasons are elevated at {ratio:.0%} of recent "
                f"closed trades ({unknown_count}/{total})."
            ),
            recommendation="Inspect exit-reason writers and reconcile ambiguous rows manually.",
            metric="unknown_exit_reason_ratio",
            value=round(ratio, 4),
            threshold=0.10,
        ))


def _check_bracket_coverage(flags: list[dict], db_path: str) -> None:
    try:
        with connect_db(db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM shadow_trades "
                "WHERE status IN ('open', 'exit_pending') "
                "AND COALESCE(quarantined, 0) = 0 "
                "AND (stop_price IS NULL OR stop_price <= 0 "
                "OR target_1 IS NULL OR target_1 <= 0)",
            ).fetchone()
    except Exception as exc:
        logger.warning("[AUDIT] Bracket-coverage precheck failed: %s", exc)
        return

    missing = int((row[0] if row else 0) or 0)
    if missing <= 0:
        return
    flags.append(_deterministic_flag(
        severity="critical",
        category="risk_governor_breach",
        description=f"{missing} open trade(s) lack valid stop/target bracket coverage.",
        recommendation=(
            "Block new entries, repair or close unprotected positions, and verify "
            "bracket writer persistence before resuming entry."
        ),
        metric="missing_bracket_coverage",
        value=missing,
        threshold=0,
    ))


def _check_reconciled_stale_volume(flags: list[dict], db_path: str) -> None:
    cutoff = (datetime.now(ET) - timedelta(hours=24)).isoformat()
    try:
        with connect_db(db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM shadow_trades "
                "WHERE status = 'closed' "
                "AND COALESCE(quarantined, 0) = 0 "
                "AND exit_reason = 'reconciled_stale' "
                "AND COALESCE(actual_exit_time, updated_at, created_at) >= ?",
                (cutoff,),
            ).fetchone()
    except Exception as exc:
        logger.warning("[AUDIT] Reconciled-stale precheck failed: %s", exc)
        return

    stale_count = int((row[0] if row else 0) or 0)
    if stale_count <= 0:
        return
    flags.append(_deterministic_flag(
        severity="warning",
        category="execution",
        description=f"{stale_count} trade(s) were auto-closed by stale reconciliation in the last 24h.",
        recommendation=(
            "Treat auto-closed stale rows as resolved reconciliation output, but inspect "
            "why the normal close path did not write terminal evidence."
        ),
        metric="reconciled_stale_closures",
        value=stale_count,
        threshold=0,
    ))


_DRAWDOWN_MIN_SAMPLE = 50
"""Minimum closed-trade sample size below which the drawdown check is suppressed.

Rationale (W21, v0.36.22): max_drawdown_pct is computed as peak-to-trough on
the cumulative P&L path over the audit window (default days=1). On small
samples a single outsized loser at the right moment in the trade ordering
trivially trips the 25% ceiling — the metric becomes order-dependent and
no longer measures strategy risk. Empirical trigger: 2026-05-18 daily audit
flagged 32.6% off a 16-trade window with profit factor 3.0, win rate 50%,
Sharpe 2.35 — a strong day where NEE's single -$207 stop dominated the path.

50 is a conservative floor — by ~50 closes the cumulative path is robust to
single-trade outliers. The proper long-term fix (queued for post-freeze) is
to switch the drawdown check to a fixed 30-day rolling window instead of
the variable audit window."""


def _check_drawdown(flags: list[dict], cto_data: dict) -> None:
    trade_summary = cto_data.get("trade_summary") or {}
    try:
        drawdown = abs(float(trade_summary.get("max_drawdown_pct") or 0))
    except (TypeError, ValueError):
        return
    trades_closed = int(trade_summary.get("trades_closed") or 0)
    if trades_closed < _DRAWDOWN_MIN_SAMPLE:
        return
    if drawdown < 25:
        return
    flags.append(_deterministic_flag(
        severity="critical",
        category="risk_governor_breach",
        description=f"Max drawdown is {drawdown:.1f}%, above the deterministic audit ceiling.",
        recommendation="Suppress new entries and review drawdown circuit-breaker state before reopening risk.",
        metric="max_drawdown_pct",
        value=round(drawdown, 2),
        threshold=25,
    ))


def _check_model_win_rate(flags: list[dict], cto_data: dict) -> None:
    by_model = cto_data.get("by_model_version") or {}
    for model_name, metrics in by_model.items():
        try:
            trades = int(metrics.get("trades") or 0)
            win_rate = float(metrics.get("win_rate") or 0)
        except (AttributeError, TypeError, ValueError):
            continue
        if trades < 2 or win_rate > 0:
            continue
        flags.append(_deterministic_flag(
            severity="critical",
            category="model",
            description=f"Model {model_name} has 0% win rate across {trades} recent closed trades.",
            recommendation=(
                "Block promotion and new entry exposure for this model until holdout, "
                "canary, and promotion gates pass with non-zero realized wins."
            ),
            metric="model_win_rate",
            value=win_rate,
            threshold=">0 with at least 2 trades",
        ))


def _check_regime_classification(db_path: str) -> dict:
    """Return regime distribution stats, excluding NULL regime_at_entry rows.

    NULL regime_at_entry means the trade pre-dates regime capture or had a
    capture failure (Track f). These are NOT 'unknown' regimes — they are
    unmeasured. Folding them into the 'unknown' bucket would inflate the
    unknown fraction and trigger false-positive audit alerts.

    Returns a dict with:
      - denominator: count of rows with non-NULL regime_at_entry
      - null_count: count excluded from denominator (observability only)
      - unknown_fraction: fraction of denominator that equals 'unknown'
      - regime_counts: breakdown of non-NULL regimes
    """
    try:
        with connect_db(db_path) as conn:
            rows = conn.execute(
                "SELECT regime_at_entry, COUNT(*) as cnt "
                "FROM shadow_trades "
                "WHERE status = 'closed' "
                "GROUP BY regime_at_entry"
            ).fetchall()
    except Exception as exc:
        logger.warning("[AUDIT] Regime classification check failed: %s", exc)
        return {"denominator": 0, "null_count": 0, "unknown_fraction": 0.0, "regime_counts": {}}

    null_count = 0
    regime_counts: dict[str, int] = {}
    for row in rows:
        regime = row[0]
        cnt = int(row[1] or 0)
        if regime is None:
            null_count += cnt
        else:
            regime_counts[regime] = cnt

    denominator = sum(regime_counts.values())
    unknown_count = regime_counts.get("unknown", 0)
    unknown_fraction = unknown_count / denominator if denominator > 0 else 0.0

    return {
        "denominator": denominator,
        "null_count": null_count,
        "unknown_fraction": round(unknown_fraction, 4),
        "regime_counts": regime_counts,
    }


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
