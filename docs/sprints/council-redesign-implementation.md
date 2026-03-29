# Council Redesign — Complete Implementation
# For review by Ryan, then commit directly or hand to CC

> This document contains the COMPLETE replacement code for the council system.
> 4 files: agents.py (rewrite), protocol.py (rewrite), engine.py (modify), value_tracker.py (new).
> All decisions from the architecture session are implemented.

---

## FILE 1: `src/council/agents.py` — Complete Rewrite

```python
"""AI Council agent definitions — vote-first protocol.

Five analytical lenses, each producing structured JSON.
Research: AI_Council_Redesign_v2__Architecture_and_Implementation.md

Agents:
  tactical_operator   — Market microstructure, short-term price action
  strategic_architect  — Portfolio theory, Kelly, phase gates
  red_team             — Adversarial pre-mortem, tail risk
  innovation_engine    — R&D pipeline, ML experiments
  macro_navigator      — Macro-financial, regulatory, structural
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

DB_PATH = "ai_research_desk.sqlite3"
ET = ZoneInfo("America/New_York")

# ── JSON output schema (shared across all agents) ────────────────
AGENT_OUTPUT_SCHEMA = """\
OUTPUT FORMAT: Respond with ONLY a JSON object (no markdown, no preamble, no code fences):
{
  "agent": "<your_agent_name>",
  "direction": "bullish" | "neutral" | "bearish",
  "confidence": <float 0.0 to 1.0>,
  "parameters": {
    "position_sizing_multiplier": <float 0.25 to 1.5>,
    "cash_reserve_target_pct": <int 10 to 50>,
    "scan_aggressiveness": "conservative" | "normal" | "aggressive"
  },
  "sector_tilts": {
    "prefer": ["sector1"],
    "avoid": ["sector2"]
  },
  "key_reasoning": "<one paragraph maximum>",
  "key_risk": "<one sentence>",
  "falsifiable_prediction": {
    "claim": "<specific testable claim>",
    "confidence": <float 0.0 to 1.0>,
    "verification_date": "YYYY-MM-DD"
  }
}
"""

# ── Agent system prompts ─────────────────────────────────────────

TACTICAL_OPERATOR_PROMPT = f"""\
You are the Tactical Operator on a five-member AI trading council for Halcyon Lab,
an autonomous equity pullback trading system on S&P 100 stocks.

ANALYTICAL FRAMEWORK:
- Market microstructure analysis: bid-ask dynamics, volume patterns, order flow signals
- Regime detection: classify current market conditions using VIX, credit spreads, trend indicators
- Short-term price action: momentum, mean reversion signals, sector rotation over 1-5 day horizons
- Volatility assessment: is vol expanding (danger) or contracting (opportunity)?

CORE QUESTION: "What does current data tell us about the next 1-5 trading days?"

EVALUATION CRITERIA:
1. Is the current regime favorable for pullback entries? (trending + moderate vol = ideal)
2. Is VIX term structure in contango (complacency) or backwardation (fear)?
3. Are recent scans finding quality setups, or is the system struggling?
4. Are open positions behaving as expected (P&L trajectory, holding time)?
5. Should we be more aggressive (more setups, larger sizes) or defensive?

{AGENT_OUTPUT_SCHEMA}
"""

STRATEGIC_ARCHITECT_PROMPT = f"""\
You are the Strategic Architect on a five-member AI trading council for Halcyon Lab,
an autonomous equity pullback trading system scaling from $100K paper to $3M AUM.

ANALYTICAL FRAMEWORK:
- Portfolio theory: diversification, risk parity, correlation management
- Kelly criterion: optimal sizing given estimated edge and variance
- Phase gate evaluation: are we on track for 50-trade gate, 100-trade gate?
- Resource allocation: where should development effort be focused?

CORE QUESTION: "Are we on track, and how should we allocate capital and attention?"

EVALUATION CRITERIA:
1. How many closed trades vs the 50-trade Phase 1 gate? Expected timeline?
2. Is the system health score (HSHS) improving or degrading?
3. Are we building the data asset fast enough? (training data growth rate)
4. Is the training pipeline healthy? (retrain frequency, quality scores, fallback rate)
5. Should we hold capital in reserve for better opportunities?

{AGENT_OUTPUT_SCHEMA}
"""

RED_TEAM_PROMPT = f"""\
You are the Red Team analyst on a five-member AI trading council for Halcyon Lab.
Your SOLE purpose is adversarial analysis. You are paid to find problems.

ANALYTICAL FRAMEWORK:
- Pre-mortem: assume the system fails in the next 30 days — what caused it?
- Tail risk: what is the worst 2-sigma event for our current positions?
- Competitive threats: are other traders crowding our signals?
- Model degradation: is the LLM producing worse analysis over time?
- Concentration risk: are positions correlated in ways we haven't measured?

CORE QUESTION: "What are we missing, and what kills us?"

EVALUATION CRITERIA:
1. What is the maximum portfolio loss if all positions move against us simultaneously?
2. Is drawdown trajectory concerning? (accelerating, decelerating, stable)
3. Are sector concentrations within safe limits even under stress?
4. Is the model's template fallback rate increasing? (sign of degradation)
5. What external event (Fed, earnings, geopolitical) could overwhelm our bracket stops?

BIAS: You are ALWAYS skeptical. When uncertain, lean bearish. When confident,
still present the counter-case. Your value is in what others miss.

{AGENT_OUTPUT_SCHEMA}
"""

INNOVATION_ENGINE_PROMPT = f"""\
You are the Innovation Engine on a five-member AI trading council for Halcyon Lab.
You focus on the ML pipeline, data quality, and technical improvements.

ANALYTICAL FRAMEWORK:
- Data-centric AI: is training data quality improving or degrading?
- Model evaluation: are quality scores, fallback rates, and calibration trending well?
- Feature engineering: are all data sources contributing signal, or is some noise?
- R&D pipeline: what should be built or investigated next?

CORE QUESTION: "What should we build or fix next, and is the ML pipeline healthy?"

EVALUATION CRITERIA:
1. Is the template fallback rate decreasing over time? (target: <10%)
2. Are training data quality scores improving? (target: avg >20/30)
3. Is the training data growing fast enough? (target: 50+ new examples/month)
4. Are there quick wins in the feature pipeline? (new data sources, better formatting)
5. Is the Saturday retrain cycle running reliably?

{AGENT_OUTPUT_SCHEMA}
"""

MACRO_NAVIGATOR_PROMPT = f"""\
You are the Macro Navigator on a five-member AI trading council for Halcyon Lab,
an autonomous equity pullback system trading S&P 100 stocks.

ANALYTICAL FRAMEWORK:
- Macro-financial analysis: yield curve, credit conditions, inflation, employment
- Economic cycle positioning: where are we in the business cycle?
- Regime change detection: identifying structural shifts before they're obvious
- Sector rotation: which sectors benefit from current macro conditions?

CORE QUESTION: "How is the world changing around us, and what regime risks exist?"

EVALUATION CRITERIA:
1. Is the yield curve signaling recession risk? (2y-10y spread, 3m-10y spread)
2. Are credit spreads widening (risk-off) or tightening (risk-on)?
3. What macro data releases are upcoming that could move markets?
4. Which sectors are aligned with current macro conditions?
5. Are there regulatory or structural changes that affect our operations?

{AGENT_OUTPUT_SCHEMA}
"""

AGENT_PROMPTS = {
    "tactical_operator": TACTICAL_OPERATOR_PROMPT,
    "strategic_architect": STRATEGIC_ARCHITECT_PROMPT,
    "red_team": RED_TEAM_PROMPT,
    "innovation_engine": INNOVATION_ENGINE_PROMPT,
    "macro_navigator": MACRO_NAVIGATOR_PROMPT,
}

AGENT_NAMES = list(AGENT_PROMPTS.keys())


# ── Data gathering functions ─────────────────────────────────────
# Each queries REAL data from SQLite. Never crashes — returns "No data" on failure.

def gather_tactical_data(db_path: str = DB_PATH) -> str:
    """Gather market microstructure and short-term data."""
    parts = []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            # VIX and term structure
            try:
                vix = conn.execute(
                    "SELECT vix_close, vix9d, vix3m FROM vix_term_structure "
                    "ORDER BY date DESC LIMIT 1"
                ).fetchone()
                if vix:
                    parts.append(f"VIX: {vix['vix_close']:.1f} | VIX9D: {vix['vix9d']:.1f} | VIX3M: {vix['vix3m']:.1f}")
                    if vix['vix_close'] and vix['vix3m']:
                        structure = "contango (complacency)" if vix['vix_close'] < vix['vix3m'] else "backwardation (fear)"
                        parts.append(f"Term structure: {structure}")
            except Exception as e:
                logger.debug("[COUNCIL] Tactical VIX query failed: %s", e)

            # Traffic Light
            try:
                tl = conn.execute(
                    "SELECT current_score, current_multiplier FROM traffic_light_state WHERE id = 1"
                ).fetchone()
                if tl:
                    parts.append(f"Traffic Light: {tl['current_score']}/6 (×{tl['current_multiplier']:.1f})")
            except Exception:
                pass

            # Recent scan results (last 3)
            try:
                scans = conn.execute(
                    "SELECT scan_time, packet_worthy, llm_success, llm_total, avg_conviction "
                    "FROM scan_metrics ORDER BY created_at DESC LIMIT 3"
                ).fetchall()
                if scans:
                    parts.append("\nRecent scans:")
                    for s in scans:
                        fb_rate = ""
                        if s['llm_total'] and s['llm_total'] > 0:
                            fb_pct = (1 - s['llm_success'] / s['llm_total']) * 100
                            fb_rate = f" fallback={fb_pct:.0f}%"
                        parts.append(f"  {s['scan_time']}: {s['packet_worthy']} packets, "
                                     f"avg conviction {s['avg_conviction']:.1f}{fb_rate}")
            except Exception as e:
                logger.debug("[COUNCIL] Tactical scan query failed: %s", e)

            # Open positions with P&L
            try:
                positions = conn.execute(
                    "SELECT ticker, pnl_pct, sector, "
                    "CAST(julianday('now') - julianday(actual_entry_time) AS INTEGER) as days_held "
                    "FROM shadow_trades WHERE status = 'open' "
                    "ORDER BY pnl_pct DESC"
                ).fetchall()
                if positions:
                    total_pnl = sum(p['pnl_pct'] or 0 for p in positions)
                    winners = sum(1 for p in positions if (p['pnl_pct'] or 0) > 0)
                    parts.append(f"\nOpen positions ({len(positions)}): {winners} green, {len(positions)-winners} red")
                    parts.append(f"Aggregate open P&L: {total_pnl:+.1f}%")
                    for p in positions[:5]:  # Top/bottom 5
                        emoji = "📈" if (p['pnl_pct'] or 0) > 0 else "📉"
                        parts.append(f"  {emoji} {p['ticker']} ({p['sector']}): {p['pnl_pct']:+.1f}% ({p['days_held']}d)")
            except Exception as e:
                logger.debug("[COUNCIL] Tactical positions query failed: %s", e)

    except Exception as e:
        logger.warning("[COUNCIL] Tactical data gathering failed: %s", e)

    return "\n".join(parts) if parts else "No tactical data available."


def gather_strategic_data(db_path: str = DB_PATH) -> str:
    """Gather portfolio strategy and phase gate data."""
    parts = []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Trade count vs gates
            try:
                closed = conn.execute(
                    "SELECT COUNT(*) as n FROM shadow_trades WHERE status = 'closed'"
                ).fetchone()
                total = conn.execute(
                    "SELECT COUNT(*) as n FROM shadow_trades"
                ).fetchone()
                n_closed = closed['n'] if closed else 0
                n_total = total['n'] if total else 0
                parts.append(f"Trade count: {n_closed} closed, {n_total - n_closed} open")
                parts.append(f"Phase 1 gate: {n_closed}/50 trades ({n_closed/50*100:.0f}%)")
            except Exception as e:
                logger.debug("[COUNCIL] Strategic trade count failed: %s", e)

            # P&L summary
            try:
                pnl = conn.execute(
                    "SELECT SUM(pnl_dollars) as total, AVG(pnl_pct) as avg_pct, "
                    "COUNT(CASE WHEN pnl_dollars > 0 THEN 1 END) as wins, "
                    "COUNT(*) as total_trades "
                    "FROM shadow_trades WHERE status = 'closed' AND pnl_dollars IS NOT NULL"
                ).fetchone()
                if pnl and pnl['total_trades'] > 0:
                    wr = pnl['wins'] / pnl['total_trades'] * 100
                    parts.append(f"Closed P&L: ${pnl['total']:.2f} total, {pnl['avg_pct']:.2f}% avg")
                    parts.append(f"Win rate: {wr:.0f}% ({pnl['wins']}/{pnl['total_trades']})")
            except Exception as e:
                logger.debug("[COUNCIL] Strategic P&L failed: %s", e)

            # Training data volume
            try:
                td = conn.execute(
                    "SELECT COUNT(*) as n, AVG(quality_score) as avg_q "
                    "FROM training_examples"
                ).fetchone()
                if td:
                    parts.append(f"\nTraining data: {td['n']} examples, avg quality {td['avg_q']:.1f}" if td['avg_q'] else f"\nTraining data: {td['n']} examples, no quality scores")
            except Exception:
                pass

            # HSHS
            try:
                from src.evaluation.hshs_live import compute_hshs
                hshs = compute_hshs(db_path)
                parts.append(f"HSHS: {hshs.get('hshs', 0):.1f}/100 (phase: {hshs.get('phase', '?')})")
                for dim, val in hshs.get("dimensions", {}).items():
                    parts.append(f"  {dim}: {val:.0f}")
            except Exception:
                pass

            # Model versions
            try:
                versions = conn.execute(
                    "SELECT COUNT(*) as n FROM model_versions"
                ).fetchone()
                parts.append(f"Model versions: {versions['n']}" if versions else "")
            except Exception:
                pass

    except Exception as e:
        logger.warning("[COUNCIL] Strategic data gathering failed: %s", e)

    return "\n".join(parts) if parts else "No strategic data available."


def gather_risk_data(db_path: str = DB_PATH) -> str:
    """Gather risk, concentration, and adversarial analysis data."""
    parts = []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Sector concentration
            try:
                sectors = conn.execute(
                    "SELECT sector, COUNT(*) as n, SUM(planned_allocation) as alloc "
                    "FROM shadow_trades WHERE status = 'open' AND sector IS NOT NULL "
                    "GROUP BY sector ORDER BY n DESC"
                ).fetchall()
                if sectors:
                    parts.append("Sector concentration (open positions):")
                    for s in sectors:
                        parts.append(f"  {s['sector']}: {s['n']} positions (${s['alloc']:.0f})" if s['alloc'] else f"  {s['sector']}: {s['n']} positions")
            except Exception as e:
                logger.debug("[COUNCIL] Risk sector query failed: %s", e)

            # Recent losses
            try:
                losses = conn.execute(
                    "SELECT ticker, pnl_pct, exit_reason, actual_exit_time "
                    "FROM shadow_trades WHERE status = 'closed' AND pnl_pct < 0 "
                    "ORDER BY actual_exit_time DESC LIMIT 5"
                ).fetchall()
                if losses:
                    parts.append("\nRecent losses:")
                    for l in losses:
                        parts.append(f"  {l['ticker']}: {l['pnl_pct']:.1f}% ({l['exit_reason']}) on {l['actual_exit_time'][:10]}")
            except Exception as e:
                logger.debug("[COUNCIL] Risk losses query failed: %s", e)

            # Model health: template fallback rate
            try:
                recent_scans = conn.execute(
                    "SELECT SUM(llm_success) as ok, SUM(llm_total) as total "
                    "FROM scan_metrics WHERE created_at > datetime('now', '-7 days')"
                ).fetchone()
                if recent_scans and recent_scans['total'] and recent_scans['total'] > 0:
                    fb_rate = (1 - recent_scans['ok'] / recent_scans['total']) * 100
                    parts.append(f"\n7-day template fallback rate: {fb_rate:.1f}%")
                    if fb_rate > 20:
                        parts.append("  ⚠️ ELEVATED — model may be degrading")
            except Exception:
                pass

            # Drawdown estimate
            try:
                equity_data = conn.execute(
                    "SELECT SUM(pnl_dollars) as cumulative FROM shadow_trades "
                    "WHERE status = 'closed'"
                ).fetchone()
                if equity_data and equity_data['cumulative']:
                    parts.append(f"\nCumulative P&L: ${equity_data['cumulative']:.2f}")
            except Exception:
                pass

    except Exception as e:
        logger.warning("[COUNCIL] Risk data gathering failed: %s", e)

    return "\n".join(parts) if parts else "No risk data available."


def gather_innovation_data(db_path: str = DB_PATH) -> str:
    """Gather ML pipeline, training data, and R&D data."""
    parts = []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Training data trends
            try:
                week_ago = (datetime.now(ET) - timedelta(days=7)).isoformat()
                month_ago = (datetime.now(ET) - timedelta(days=30)).isoformat()

                total = conn.execute("SELECT COUNT(*) as n FROM training_examples").fetchone()
                new_week = conn.execute(
                    "SELECT COUNT(*) as n FROM training_examples WHERE created_at > ?", (week_ago,)
                ).fetchone()
                new_month = conn.execute(
                    "SELECT COUNT(*) as n FROM training_examples WHERE created_at > ?", (month_ago,)
                ).fetchone()

                parts.append(f"Training data: {total['n']} total, +{new_week['n']} this week, +{new_month['n']} this month")
            except Exception:
                pass

            # Quality score distribution
            try:
                q_stats = conn.execute(
                    "SELECT AVG(quality_score) as avg, MIN(quality_score) as min, MAX(quality_score) as max, "
                    "COUNT(CASE WHEN quality_score IS NULL OR quality_score = 0 THEN 1 END) as unscored "
                    "FROM training_examples"
                ).fetchone()
                if q_stats:
                    parts.append(f"Quality scores: avg={q_stats['avg']:.1f}, range=[{q_stats['min']:.0f}, {q_stats['max']:.0f}], {q_stats['unscored']} unscored")
            except Exception:
                pass

            # Source distribution
            try:
                sources = conn.execute(
                    "SELECT source, COUNT(*) as n FROM training_examples "
                    "GROUP BY source ORDER BY n DESC"
                ).fetchall()
                if sources:
                    parts.append("\nTraining data sources:")
                    for s in sources:
                        parts.append(f"  {s['source'] or 'unknown'}: {s['n']}")
            except Exception:
                pass

            # Curriculum stage distribution
            try:
                stages = conn.execute(
                    "SELECT curriculum_stage, COUNT(*) as n FROM training_examples "
                    "WHERE curriculum_stage IS NOT NULL GROUP BY curriculum_stage"
                ).fetchall()
                if stages:
                    parts.append("\nCurriculum stages:")
                    for s in stages:
                        parts.append(f"  {s['curriculum_stage']}: {s['n']}")
            except Exception:
                pass

            # Template fallback trend
            try:
                fb_trend = conn.execute(
                    "SELECT DATE(created_at) as day, "
                    "CAST(SUM(llm_total - llm_success) AS FLOAT) / SUM(llm_total) * 100 as fb_pct "
                    "FROM scan_metrics WHERE llm_total > 0 "
                    "GROUP BY DATE(created_at) ORDER BY day DESC LIMIT 7"
                ).fetchall()
                if fb_trend:
                    parts.append("\nFallback rate trend (last 7 days):")
                    for f in fb_trend:
                        parts.append(f"  {f['day']}: {f['fb_pct']:.1f}%")
            except Exception:
                pass

    except Exception as e:
        logger.warning("[COUNCIL] Innovation data gathering failed: %s", e)

    return "\n".join(parts) if parts else "No innovation data available."


def gather_macro_data(db_path: str = DB_PATH) -> str:
    """Gather macroeconomic, regime, and structural data."""
    parts = []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Key macro indicators from FRED
            try:
                indicators = [
                    ("DFF", "Fed Funds Rate"),
                    ("T10Y2Y", "10Y-2Y Spread"),
                    ("T10Y3M", "10Y-3M Spread"),
                    ("BAMLH0A0HYM2", "HY Spread (OAS)"),
                    ("UNRATE", "Unemployment Rate"),
                    ("CPIAUCSL", "CPI (YoY)"),
                ]
                macro_lines = []
                for series_id, label in indicators:
                    row = conn.execute(
                        "SELECT value, date FROM macro_snapshots "
                        "WHERE series_id = ? ORDER BY date DESC LIMIT 1",
                        (series_id,)
                    ).fetchone()
                    if row:
                        macro_lines.append(f"  {label}: {row['value']:.2f} (as of {row['date']})")
                if macro_lines:
                    parts.append("Key macro indicators:")
                    parts.extend(macro_lines)
            except Exception as e:
                logger.debug("[COUNCIL] Macro indicators failed: %s", e)

            # Yield curve status
            try:
                spread_10y2y = conn.execute(
                    "SELECT value FROM macro_snapshots WHERE series_id = 'T10Y2Y' ORDER BY date DESC LIMIT 1"
                ).fetchone()
                if spread_10y2y:
                    val = spread_10y2y['value']
                    if val < 0:
                        parts.append(f"\n⚠️ Yield curve INVERTED ({val:.2f}%) — recession signal")
                    elif val < 0.5:
                        parts.append(f"\nYield curve flat ({val:.2f}%) — watch for inversion")
                    else:
                        parts.append(f"\nYield curve normal ({val:.2f}%)")
            except Exception:
                pass

            # Credit conditions
            try:
                hy = conn.execute(
                    "SELECT value FROM macro_snapshots WHERE series_id = 'BAMLH0A0HYM2' ORDER BY date DESC LIMIT 1"
                ).fetchone()
                hy_avg = conn.execute(
                    "SELECT AVG(value) FROM macro_snapshots WHERE series_id = 'BAMLH0A0HYM2' AND date > date('now', '-365 days')"
                ).fetchone()
                if hy and hy_avg and hy_avg[0]:
                    z = (hy['value'] - hy_avg[0]) / max(0.1, abs(hy_avg[0] * 0.1))
                    status = "tight" if z < 0 else "normal" if z < 1 else "widening" if z < 2 else "stress"
                    parts.append(f"Credit conditions: {status} (HY OAS z-score ~{z:.1f})")
            except Exception:
                pass

            # Sector rotation (from recent scan data)
            try:
                sector_perf = conn.execute(
                    "SELECT sector, AVG(pnl_pct) as avg_pnl, COUNT(*) as n "
                    "FROM shadow_trades WHERE status = 'closed' AND sector IS NOT NULL "
                    "GROUP BY sector HAVING n >= 2 ORDER BY avg_pnl DESC"
                ).fetchall()
                if sector_perf:
                    parts.append("\nSector performance (closed trades):")
                    for s in sector_perf:
                        emoji = "🟢" if s['avg_pnl'] > 0 else "🔴"
                        parts.append(f"  {emoji} {s['sector']}: {s['avg_pnl']:+.1f}% avg ({s['n']} trades)")
            except Exception:
                pass

    except Exception as e:
        logger.warning("[COUNCIL] Macro data gathering failed: %s", e)

    return "\n".join(parts) if parts else "No macro data available."


AGENT_DATA_FUNCTIONS = {
    "tactical_operator": gather_tactical_data,
    "strategic_architect": gather_strategic_data,
    "red_team": gather_risk_data,
    "innovation_engine": gather_innovation_data,
    "macro_navigator": gather_macro_data,
}
```

---

## FILE 2: `src/council/protocol.py` — Complete Rewrite

```python
"""Council protocol — vote-first Modified Delphi.

Round 1: All 5 agents assess independently (always runs).
Aggregate: Confidence-weighted voting with domain weights.
Round 2: Only if <3/5 consensus. Agents see others' views. (conditional)

Research: AI_Council_Redesign_v2__Architecture_and_Implementation.md
NeurIPS 2025: majority voting > multi-agent debate for factual tasks.
"""

import json
import logging
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# ── Domain weights by session type ────────────────────────────────
DOMAIN_WEIGHTS = {
    "daily": {
        "tactical_operator": 1.2,
        "strategic_architect": 0.8,
        "red_team": 1.0,
        "innovation_engine": 0.6,
        "macro_navigator": 0.9,
    },
    "weekly": {
        "tactical_operator": 0.8,
        "strategic_architect": 1.3,
        "red_team": 1.0,
        "innovation_engine": 1.0,
        "macro_navigator": 1.2,
    },
    "monthly": {
        "tactical_operator": 0.6,
        "strategic_architect": 1.5,
        "red_team": 1.0,
        "innovation_engine": 1.2,
        "macro_navigator": 1.3,
    },
}

# ── Decision thresholds (hardcoded per architecture decision) ─────
# To modify: edit this dict. Do NOT move to settings.yaml.
DECISION_THRESHOLDS = {
    "strong_bullish": 0.5,      # score > 0.5
    "lean_bullish": 0.2,        # 0.2 < score <= 0.5
    "neutral_low": -0.2,        # -0.2 <= score <= 0.2
    "lean_bearish": -0.5,       # -0.5 <= score < -0.2
    # score < -0.5 = strong bearish
}

# ── Rate limiters for parameter auto-application ──────────────────
RATE_LIMITS = {
    "max_daily_change_pct": 0.25,      # ±25% per day
    "max_weekly_change_pct": 0.50,     # ±50% cumulative per week
    "min_confidence_to_apply": 0.40,   # Below this → all params stay default
    "emergency_reset_streak": 3,        # 3 consecutive disagreements → reset
}

# ── Parameter bounds (hard limits) ────────────────────────────────
PARAMETER_BOUNDS = {
    "position_sizing_multiplier": (0.25, 1.5),
    "cash_reserve_target_pct": (10, 50),
    "scan_aggressiveness": ("conservative", "normal", "aggressive"),
}

PARAMETER_DEFAULTS = {
    "position_sizing_multiplier": 1.0,
    "cash_reserve_target_pct": 15,
    "scan_aggressiveness": "normal",
}

DIRECTION_MAP = {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}


def _call_claude(system_prompt: str, user_message: str) -> str | None:
    """Call Claude API and return raw response text."""
    try:
        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text if response.content else None
    except Exception as e:
        logger.error("[COUNCIL] Claude API call failed: %s", e)
        return None


def _parse_agent_response(raw: str | None, agent_name: str) -> dict:
    """Parse structured JSON from agent response.

    Returns parsed dict on success, default response on failure.
    Always logs parse failures with the raw response for debugging.
    """
    if not raw:
        logger.warning("[COUNCIL] Empty response from %s", agent_name)
        return _default_response(agent_name, "Empty API response")

    # Strip markdown code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first and last lines (fences)
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()

    try:
        parsed = json.loads(cleaned)
        # Validate required fields
        if "direction" not in parsed or "confidence" not in parsed:
            logger.warning("[COUNCIL] %s response missing required fields: %s", agent_name, list(parsed.keys()))
            return _default_response(agent_name, "Missing direction or confidence")
        # Clamp confidence
        parsed["confidence"] = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
        # Ensure agent name
        parsed["agent"] = agent_name
        return parsed
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("[COUNCIL] JSON parse failed for %s: %s\nRaw response: %s",
                       agent_name, e, raw[:500])
        return _default_response(agent_name, f"JSON parse error: {e}")


def _default_response(agent_name: str, reason: str = "") -> dict:
    """Produce a safe default response when an agent fails."""
    return {
        "agent": agent_name,
        "direction": "neutral",
        "confidence": 0.1,
        "parameters": PARAMETER_DEFAULTS.copy(),
        "sector_tilts": {"prefer": [], "avoid": []},
        "key_reasoning": f"Agent response unavailable: {reason}" if reason else "Agent response unavailable",
        "key_risk": "Unable to assess",
        "falsifiable_prediction": None,
        "_parse_failed": True,
    }


def build_shared_context(db_path: str = "ai_research_desk.sqlite3") -> str:
    """Build shared market context for all agents.

    Each agent also gets its own specialist data via gather_*_data().
    This shared context provides the common baseline.
    """
    parts = [f"Session date: {datetime.now(ET).strftime('%Y-%m-%d %H:%M ET')}"]

    try:
        with sqlite3.connect(db_path) as conn:
            # Open position count
            try:
                row = conn.execute("SELECT COUNT(*) as n FROM shadow_trades WHERE status = 'open'").fetchone()
                parts.append(f"Open positions: {row[0]}")
            except Exception:
                pass

            # VIX
            try:
                row = conn.execute("SELECT vix_close FROM vix_term_structure ORDER BY date DESC LIMIT 1").fetchone()
                if row:
                    parts.append(f"VIX: {row[0]:.1f}")
            except Exception:
                pass

            # Traffic Light
            try:
                row = conn.execute("SELECT current_score, current_multiplier FROM traffic_light_state WHERE id = 1").fetchone()
                if row:
                    parts.append(f"Traffic Light: {row[0]}/6 (×{row[1]:.1f})")
            except Exception:
                pass

            # HSHS
            try:
                from src.evaluation.hshs_live import compute_hshs
                hshs = compute_hshs(db_path)
                parts.append(f"System Health (HSHS): {hshs.get('hshs', 0):.1f}/100")
            except Exception:
                pass

    except Exception as e:
        logger.warning("[COUNCIL] Shared context build failed: %s", e)

    return "\n".join(parts)


def run_round_1(
    shared_context: str,
    db_path: str = "ai_research_desk.sqlite3",
) -> list[dict]:
    """Round 1: All agents assess independently. Always runs.

    Returns list of 5 parsed agent assessments.
    """
    from src.council.agents import AGENT_PROMPTS, AGENT_DATA_FUNCTIONS

    assessments = []
    for agent_name, system_prompt in AGENT_PROMPTS.items():
        # Gather agent-specific data
        data_fn = AGENT_DATA_FUNCTIONS.get(agent_name)
        agent_data = data_fn(db_path) if data_fn else "No specialist data available."

        user_message = f"""SHARED MARKET CONTEXT:
{shared_context}

YOUR SPECIALIST DATA:
{agent_data}

Produce your assessment as a JSON object. No preamble, no markdown fences."""

        raw = _call_claude(system_prompt, user_message)
        parsed = _parse_agent_response(raw, agent_name)
        assessments.append(parsed)

    return assessments


def aggregate_votes(
    assessments: list[dict],
    session_type: str = "daily",
) -> dict:
    """Compute confidence-weighted aggregated vote.

    Returns:
        {
            "aggregated_score": float (-1.0 to 1.0),
            "direction": "bullish"|"neutral"|"bearish",
            "confidence_avg": float,
            "vote_distribution": {"bullish": N, "neutral": N, "bearish": N},
            "consensus_reached": bool (>=3/5 agree),
            "consensus_type": "5-0"|"4-1"|"3-2"|"no_consensus",
            "round2_needed": bool,
            "parameter_recommendations": dict (aggregated from agents),
        }
    """
    weights = DOMAIN_WEIGHTS.get(session_type, DOMAIN_WEIGHTS["daily"])

    numerator = 0.0
    denominator = 0.0
    vote_dist = {"bullish": 0, "neutral": 0, "bearish": 0}
    confidences = []

    # Aggregate parameter recommendations (confidence-weighted average)
    param_num = {"position_sizing_multiplier": 0.0, "cash_reserve_target_pct": 0.0}
    param_den = 0.0

    for a in assessments:
        agent = a.get("agent", "unknown")
        direction = a.get("direction", "neutral")
        confidence = max(0.0, min(1.0, float(a.get("confidence", 0.5))))
        domain_weight = weights.get(agent, 1.0)

        vote = DIRECTION_MAP.get(direction, 0.0)
        w = confidence * domain_weight
        numerator += vote * w
        denominator += w
        vote_dist[direction] = vote_dist.get(direction, 0) + 1
        confidences.append(confidence)

        # Aggregate parameters
        params = a.get("parameters", {})
        for pname in param_num:
            pval = params.get(pname, PARAMETER_DEFAULTS.get(pname, 1.0))
            param_num[pname] += float(pval) * w
        param_den += w

    score = numerator / denominator if denominator > 0 else 0.0
    confidence_avg = sum(confidences) / len(confidences) if confidences else 0.0

    # Consensus check
    max_votes = max(vote_dist.values()) if vote_dist else 0
    total_agents = len(assessments)
    winning_direction = max(vote_dist, key=vote_dist.get) if vote_dist else "neutral"

    if max_votes >= 4:
        consensus_type = f"{max_votes}-{total_agents - max_votes}"
    elif max_votes >= 3:
        consensus_type = f"{max_votes}-{total_agents - max_votes}"
    else:
        consensus_type = "no_consensus"

    consensus_reached = max_votes >= 3

    # Direction from score
    if score > DECISION_THRESHOLDS["lean_bullish"]:
        direction = "bullish"
    elif score < DECISION_THRESHOLDS["neutral_low"]:
        direction = "bearish"
    else:
        direction = "neutral"

    # Aggregated parameter recommendations
    param_recs = {}
    if param_den > 0:
        for pname in param_num:
            param_recs[pname] = round(param_num[pname] / param_den, 2)
    param_recs["scan_aggressiveness"] = _aggregate_scan_aggressiveness(assessments, weights)

    return {
        "aggregated_score": round(score, 4),
        "direction": direction,
        "confidence_avg": round(confidence_avg, 3),
        "vote_distribution": vote_dist,
        "consensus_reached": consensus_reached,
        "consensus_type": consensus_type,
        "round2_needed": not consensus_reached,
        "parameter_recommendations": param_recs,
    }


def _aggregate_scan_aggressiveness(assessments: list[dict], weights: dict) -> str:
    """Aggregate scan aggressiveness via weighted majority vote."""
    scores = {"conservative": 0.0, "normal": 0.0, "aggressive": 0.0}
    for a in assessments:
        agent = a.get("agent", "unknown")
        params = a.get("parameters", {})
        agg = params.get("scan_aggressiveness", "normal")
        if agg in scores:
            w = weights.get(agent, 1.0) * a.get("confidence", 0.5)
            scores[agg] += w
    return max(scores, key=scores.get)


def run_round_2(
    round1_assessments: list[dict],
    shared_context: str,
    db_path: str = "ai_research_desk.sqlite3",
) -> tuple[list[dict], list[str]]:
    """Round 2: Agents see others' views and can update. Conditional.

    Returns:
        (updated_assessments, sycophancy_flags)
        sycophancy_flags: list of agent names that flipped direction
    """
    from src.council.agents import AGENT_PROMPTS

    # Build summary of Round 1 for all agents to see
    r1_summary_lines = ["ROUND 1 RESULTS (other agents' assessments):"]
    for a in round1_assessments:
        r1_summary_lines.append(
            f"  {a.get('agent', '?')}: {a.get('direction', '?')} "
            f"(confidence {a.get('confidence', 0):.2f}) — {a.get('key_reasoning', '')[:100]}"
        )
    r1_summary = "\n".join(r1_summary_lines)

    # Track original directions for sycophancy detection
    original_directions = {a["agent"]: a.get("direction", "neutral") for a in round1_assessments}

    updated = []
    sycophancy_flags = []

    for a in round1_assessments:
        agent_name = a["agent"]
        system_prompt = AGENT_PROMPTS.get(agent_name, "")

        user_message = f"""SHARED CONTEXT:
{shared_context}

{r1_summary}

You previously assessed: {a.get('direction', 'neutral')} with confidence {a.get('confidence', 0):.2f}.
Your reasoning: {a.get('key_reasoning', '')}

After seeing others' views, you may update your assessment or maintain your position.
If you change direction, explain why the new evidence changed your mind.
Produce your UPDATED assessment as a JSON object."""

        raw = _call_claude(system_prompt, user_message)
        parsed = _parse_agent_response(raw, agent_name)
        updated.append(parsed)

        # Sycophancy detection
        if parsed.get("direction") != original_directions.get(agent_name):
            sycophancy_flags.append(agent_name)
            logger.info("[COUNCIL] SYCOPHANCY FLAG: %s flipped from %s to %s",
                        agent_name, original_directions[agent_name], parsed.get("direction"))

    return updated, sycophancy_flags


def apply_rate_limiters(
    recommended: dict,
    current: dict,
    db_path: str = "ai_research_desk.sqlite3",
) -> dict:
    """Apply rate limiters to parameter recommendations.

    Args:
        recommended: {"position_sizing_multiplier": X, "cash_reserve_target_pct": Y, ...}
        current: current active parameter values (same keys)

    Returns:
        dict with same keys, values clipped by rate limiters.
        Extra key "_rate_limited" = True if any value was clipped.
    """
    applied = {}
    rate_limited = False

    for param, rec_val in recommended.items():
        if param == "scan_aggressiveness":
            applied[param] = rec_val  # Categorical — no rate limiting
            continue

        curr_val = current.get(param, PARAMETER_DEFAULTS.get(param, 1.0))
        rec_val = float(rec_val)
        curr_val = float(curr_val)

        # Clamp to hard bounds
        bounds = PARAMETER_BOUNDS.get(param)
        if bounds and isinstance(bounds, tuple) and len(bounds) == 2:
            rec_val = max(bounds[0], min(bounds[1], rec_val))

        # Rate limit: max ±25% daily change
        max_change = abs(curr_val) * RATE_LIMITS["max_daily_change_pct"]
        if max_change < 0.01:
            max_change = 0.25  # Minimum change threshold

        if abs(rec_val - curr_val) > max_change:
            # Clip to max allowed change
            if rec_val > curr_val:
                rec_val = curr_val + max_change
            else:
                rec_val = curr_val - max_change
            rate_limited = True
            logger.info("[COUNCIL] Rate limited %s: recommended=%.2f, applied=%.2f (max change=%.2f)",
                        param, recommended[param], rec_val, max_change)

        applied[param] = round(rec_val, 3)

    applied["_rate_limited"] = rate_limited
    return applied


def tally_votes(assessments: list[dict], session_type: str = "daily") -> dict:
    """Convenience wrapper — aggregate votes and compute final result."""
    return aggregate_votes(assessments, session_type)
```

---

## FILE 3: `src/council/value_tracker.py` — NEW

```python
"""Council value tracking — counterfactual P&L computation.

Tracks whether council parameter adjustments create or destroy value
by comparing actual P&L (with council adjustments) to counterfactual
P&L (what would have happened with default parameters).

Architecture: AI_Council_Redesign_v2__Architecture_and_Implementation.md
Decision: Both holistic + per-agent value tracking from day 1.
"""

import logging
import sqlite3
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
DB_PATH = "ai_research_desk.sqlite3"

SCHEMA = """\
CREATE TABLE IF NOT EXISTS council_parameter_log (
    log_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    agent_name TEXT,
    parameter_name TEXT NOT NULL,
    default_value REAL NOT NULL,
    council_value REAL NOT NULL,
    applied_value REAL NOT NULL,
    rate_limited INTEGER DEFAULT 0,
    attribution_start TEXT NOT NULL,
    attribution_end TEXT,
    trades_during_window INTEGER DEFAULT 0,
    pnl_during_window REAL,
    counterfactual_pnl REAL,
    value_added_dollars REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS council_parameter_state (
    parameter_name TEXT PRIMARY KEY,
    current_value REAL NOT NULL,
    default_value REAL NOT NULL,
    last_session_id TEXT,
    last_updated TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_param_log_session
    ON council_parameter_log(session_id);
CREATE INDEX IF NOT EXISTS idx_param_log_window
    ON council_parameter_log(attribution_start, attribution_end);
"""


def init_value_tables(db_path: str = DB_PATH) -> None:
    """Create value tracking tables."""
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)


def get_current_parameters(db_path: str = DB_PATH) -> dict:
    """Get current active council parameter values."""
    from src.council.protocol import PARAMETER_DEFAULTS

    defaults = PARAMETER_DEFAULTS.copy()
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT parameter_name, current_value FROM council_parameter_state").fetchall()
            for row in rows:
                defaults[row["parameter_name"]] = row["current_value"]
    except Exception:
        pass
    return defaults


def log_parameter_change(
    session_id: str,
    parameter_name: str,
    default_value: float,
    council_value: float,
    applied_value: float,
    rate_limited: bool = False,
    agent_name: str | None = None,
    db_path: str = DB_PATH,
) -> str:
    """Log a council parameter change for value tracking.

    Closes the previous attribution window for this parameter.
    Returns the log_id.
    """
    log_id = str(uuid.uuid4())
    now = datetime.now(ET).isoformat()

    try:
        with sqlite3.connect(db_path) as conn:
            # Close previous attribution window
            conn.execute(
                "UPDATE council_parameter_log SET attribution_end = ? "
                "WHERE parameter_name = ? AND attribution_end IS NULL",
                (now, parameter_name),
            )

            # Insert new log entry
            conn.execute(
                "INSERT INTO council_parameter_log "
                "(log_id, session_id, agent_name, parameter_name, default_value, "
                "council_value, applied_value, rate_limited, attribution_start, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (log_id, session_id, agent_name, parameter_name,
                 default_value, council_value, applied_value,
                 1 if rate_limited else 0, now, now),
            )

            # Update current state
            conn.execute(
                "INSERT OR REPLACE INTO council_parameter_state "
                "(parameter_name, current_value, default_value, last_session_id, last_updated) "
                "VALUES (?, ?, ?, ?, ?)",
                (parameter_name, applied_value, default_value, session_id, now),
            )

    except Exception as e:
        logger.error("[VALUE] Failed to log parameter change: %s", e)

    return log_id


def compute_attribution(db_path: str = DB_PATH) -> dict:
    """Compute value attribution for all closed attribution windows.

    For position_sizing_multiplier:
    - Actual P&L = trade P&L at council-adjusted size
    - Counterfactual P&L = trade P&L at default size
    - Value added = actual - counterfactual

    Returns:
        {
            "total_value_added": float,
            "windows_computed": int,
            "per_parameter": {param_name: {"value_added": float, "trades": int}},
            "per_agent": {agent_name: {"value_added": float, "recommendations": int}},
        }
    """
    result = {
        "total_value_added": 0.0,
        "windows_computed": 0,
        "per_parameter": {},
        "per_agent": {},
    }

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Find closed windows that haven't been computed
            windows = conn.execute(
                "SELECT * FROM council_parameter_log "
                "WHERE attribution_end IS NOT NULL AND value_added_dollars IS NULL"
            ).fetchall()

            for window in windows:
                param = window["parameter_name"]
                start = window["attribution_start"]
                end = window["attribution_end"]
                applied = window["applied_value"]
                default = window["default_value"]

                if param == "position_sizing_multiplier" and default > 0:
                    # Find trades opened during this window
                    trades = conn.execute(
                        "SELECT pnl_dollars, pnl_pct, planned_allocation FROM shadow_trades "
                        "WHERE status = 'closed' AND actual_entry_time >= ? AND actual_entry_time < ?",
                        (start, end),
                    ).fetchall()

                    if trades:
                        actual_pnl = sum(t["pnl_dollars"] or 0 for t in trades)
                        # Counterfactual: what if default sizing had been used?
                        sizing_ratio = default / applied if applied > 0 else 1.0
                        counterfactual_pnl = sum(
                            (t["pnl_dollars"] or 0) * sizing_ratio for t in trades
                        )
                        value_added = actual_pnl - counterfactual_pnl

                        conn.execute(
                            "UPDATE council_parameter_log SET "
                            "trades_during_window = ?, pnl_during_window = ?, "
                            "counterfactual_pnl = ?, value_added_dollars = ? "
                            "WHERE log_id = ?",
                            (len(trades), actual_pnl, counterfactual_pnl,
                             value_added, window["log_id"]),
                        )

                        result["total_value_added"] += value_added
                        result["windows_computed"] += 1

                        # Per-parameter tracking
                        if param not in result["per_parameter"]:
                            result["per_parameter"][param] = {"value_added": 0.0, "trades": 0}
                        result["per_parameter"][param]["value_added"] += value_added
                        result["per_parameter"][param]["trades"] += len(trades)

                        # Per-agent tracking
                        agent = window["agent_name"] or "consensus"
                        if agent not in result["per_agent"]:
                            result["per_agent"][agent] = {"value_added": 0.0, "recommendations": 0}
                        result["per_agent"][agent]["value_added"] += value_added
                        result["per_agent"][agent]["recommendations"] += 1

    except Exception as e:
        logger.error("[VALUE] Attribution computation failed: %s", e)

    return result


def get_rolling_value_summary(days: int = 30, db_path: str = DB_PATH) -> dict:
    """Get rolling N-day council value summary.

    Returns:
        {
            "period_days": int,
            "total_value_added": float,
            "total_trades_influenced": int,
            "per_parameter": {...},
            "per_agent": {...},
            "weeks_negative": int (consecutive),
            "authority_status": "full"|"reduced"|"alert",
        }
    """
    cutoff = (datetime.now(ET) - timedelta(days=days)).isoformat()
    summary = {
        "period_days": days,
        "total_value_added": 0.0,
        "total_trades_influenced": 0,
        "per_parameter": {},
        "per_agent": {},
        "weeks_negative": 0,
        "authority_status": "full",
    }

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            rows = conn.execute(
                "SELECT parameter_name, agent_name, value_added_dollars, trades_during_window "
                "FROM council_parameter_log "
                "WHERE attribution_start >= ? AND value_added_dollars IS NOT NULL",
                (cutoff,),
            ).fetchall()

            for r in rows:
                va = r["value_added_dollars"] or 0
                trades = r["trades_during_window"] or 0
                summary["total_value_added"] += va
                summary["total_trades_influenced"] += trades

                param = r["parameter_name"]
                if param not in summary["per_parameter"]:
                    summary["per_parameter"][param] = {"value_added": 0.0, "trades": 0}
                summary["per_parameter"][param]["value_added"] += va
                summary["per_parameter"][param]["trades"] += trades

                agent = r["agent_name"] or "consensus"
                if agent not in summary["per_agent"]:
                    summary["per_agent"][agent] = {"value_added": 0.0, "recommendations": 0}
                summary["per_agent"][agent]["value_added"] += va
                summary["per_agent"][agent]["recommendations"] += 1

            # Compute consecutive weeks negative
            # Check each of the last 12 weeks
            for w in range(12):
                week_start = (datetime.now(ET) - timedelta(weeks=w+1)).isoformat()
                week_end = (datetime.now(ET) - timedelta(weeks=w)).isoformat()
                week_va = conn.execute(
                    "SELECT COALESCE(SUM(value_added_dollars), 0) FROM council_parameter_log "
                    "WHERE attribution_start >= ? AND attribution_start < ? AND value_added_dollars IS NOT NULL",
                    (week_start, week_end),
                ).fetchone()
                if week_va and week_va[0] < 0:
                    summary["weeks_negative"] += 1
                else:
                    break  # Stop at first non-negative week

            # Authority status
            if summary["weeks_negative"] >= 12:
                summary["authority_status"] = "reduced"  # Auto-tighten bounds
            elif summary["weeks_negative"] >= 8:
                summary["authority_status"] = "alert"    # Alert but full authority
            else:
                summary["authority_status"] = "full"

    except Exception as e:
        logger.error("[VALUE] Rolling summary failed: %s", e)

    return summary
```

---

## FILE 4: `src/council/engine.py` — Modifications

The engine.py needs these changes to the existing `CouncilEngine.run_session()` method:

1. Add `result_json TEXT` column to council_sessions (safe ALTER)
2. Call `aggregate_votes()` after Round 1
3. Only proceed to Round 2 if `round2_needed`
4. Store structured JSON in `result_json`
5. Log parameter changes via value_tracker
6. Extract and store calibration predictions

**The key change to `run_session()`:**

Replace the current always-3-rounds flow with:

```python
    def run_session(
        self,
        session_type: str = "daily",
        trigger_reason: str | None = None,
    ) -> dict:
        """Run a vote-first council session.

        Round 1 always runs. Round 2 only if <3/5 consensus.
        Daily sessions never run Round 3.
        """
        session_id = str(uuid.uuid4())
        created_at = datetime.now(ET).isoformat()

        logger.info("Starting council session %s (type=%s)", session_id, session_type)

        # Create session record
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO council_sessions
                   (session_id, session_type, trigger_reason, created_at, rounds_completed)
                   VALUES (?, ?, ?, ?, 0)""",
                (session_id, session_type, trigger_reason, created_at),
            )
            conn.commit()

        # Build shared context
        shared_context = build_shared_context(self.db_path)

        # ── Round 1: Independent assessment (always) ──
        round1 = []
        try:
            round1 = run_round_1(shared_context, db_path=self.db_path)
            with sqlite3.connect(self.db_path) as conn:
                _store_votes(conn, session_id, 1, round1)
                conn.execute(
                    "UPDATE council_sessions SET rounds_completed = 1 WHERE session_id = ?",
                    (session_id,),
                )
                conn.commit()
        except Exception as e:
            logger.error("Round 1 failed: %s", e)
            return self._finalize_session(session_id, 0, [], session_type)

        # ── Aggregate Round 1 ──
        aggregation = aggregate_votes(round1, session_type)
        rounds_completed = 1
        sycophancy_flags = []
        final_assessments = round1

        # ── Round 2: Only if no consensus ──
        if aggregation["round2_needed"]:
            try:
                round2, sycophancy_flags = run_round_2(round1, shared_context, self.db_path)
                rounds_completed = 2
                final_assessments = round2
                # Re-aggregate with updated assessments
                aggregation = aggregate_votes(round2, session_type)
                with sqlite3.connect(self.db_path) as conn:
                    _store_votes(conn, session_id, 2, round2)
                    conn.execute(
                        "UPDATE council_sessions SET rounds_completed = 2 WHERE session_id = ?",
                        (session_id,),
                    )
                    conn.commit()
            except Exception as e:
                logger.error("Round 2 failed: %s", e)

        # ── Apply parameters with rate limiters ──
        from src.council.value_tracker import get_current_parameters, log_parameter_change
        from src.council.protocol import apply_rate_limiters, PARAMETER_DEFAULTS

        current_params = get_current_parameters(self.db_path)
        recommended = aggregation.get("parameter_recommendations", {})
        applied = apply_rate_limiters(recommended, current_params, self.db_path)

        # Low confidence override: if avg confidence < threshold, use defaults
        from src.council.protocol import RATE_LIMITS
        if aggregation["confidence_avg"] < RATE_LIMITS["min_confidence_to_apply"]:
            applied = PARAMETER_DEFAULTS.copy()
            applied["_rate_limited"] = True
            logger.info("[COUNCIL] Low confidence (%.2f < %.2f) — using defaults",
                        aggregation["confidence_avg"], RATE_LIMITS["min_confidence_to_apply"])

        # Log parameter changes for value tracking
        rate_limited = applied.pop("_rate_limited", False)
        for param_name, applied_val in applied.items():
            if param_name == "scan_aggressiveness":
                continue  # Categorical — logged separately
            default_val = PARAMETER_DEFAULTS.get(param_name, 1.0)
            council_val = recommended.get(param_name, default_val)
            # Determine which agent drove this recommendation (highest weight)
            # Simplified: use the agent whose recommendation was closest to the aggregate
            driving_agent = "consensus"
            log_parameter_change(
                session_id=session_id,
                parameter_name=param_name,
                default_value=float(default_val),
                council_value=float(council_val),
                applied_value=float(applied_val),
                rate_limited=rate_limited,
                agent_name=driving_agent,
                db_path=self.db_path,
            )

        # ── Extract and store calibration predictions ──
        for assessment in final_assessments:
            pred = assessment.get("falsifiable_prediction")
            if pred and isinstance(pred, dict) and pred.get("claim"):
                try:
                    with sqlite3.connect(self.db_path) as conn:
                        conn.execute(
                            "INSERT INTO council_calibrations "
                            "(calibration_id, session_id, agent_name, prediction, "
                            "prediction_confidence, verification_date, created_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (str(uuid.uuid4()), session_id, assessment["agent"],
                             pred["claim"], pred.get("confidence", 0.5),
                             pred.get("verification_date", ""),
                             datetime.now(ET).isoformat()),
                        )
                except Exception as e:
                    logger.warning("[COUNCIL] Calibration insert failed: %s", e)

        # ── Build and store structured session result ──
        dissent = [
            {
                "agent": a["agent"],
                "direction": a.get("direction"),
                "confidence": a.get("confidence"),
                "key_reasoning": a.get("key_reasoning", ""),
            }
            for a in final_assessments
            if a.get("direction") != aggregation["direction"]
        ]

        result_json = {
            "session_meta": {
                "session_id": session_id,
                "session_type": session_type,
                "cost_usd": _estimate_session_cost(rounds_completed),
                "rounds_completed": rounds_completed,
            },
            "market_context": {
                "shared_context": shared_context,
            },
            "votes": {
                "aggregated_score": aggregation["aggregated_score"],
                "direction": aggregation["direction"],
                "confidence_avg": aggregation["confidence_avg"],
                "vote_distribution": aggregation["vote_distribution"],
                "consensus_reached": aggregation["consensus_reached"],
                "consensus_type": aggregation["consensus_type"],
                "round2_triggered": rounds_completed > 1,
                "sycophancy_flags": sycophancy_flags,
            },
            "parameter_adjustments": {
                k: {
                    "previous": current_params.get(k),
                    "recommended": recommended.get(k),
                    "applied": applied.get(k),
                    "rate_limited": rate_limited,
                }
                for k in applied if k != "scan_aggressiveness"
            },
            "agent_assessments": final_assessments,
            "dissent": dissent,
        }

        return self._finalize_session(
            session_id, rounds_completed, final_assessments,
            session_type, result_json, applied,
        )
```

**Also update `_finalize_session`** to accept and store `result_json` and `applied_params`.

**Add safe ALTER in `init_council_tables()`:**
```python
    # Safe column additions
    for alter in [
        "ALTER TABLE council_sessions ADD COLUMN result_json TEXT",
    ]:
        try:
            conn.execute(alter)
        except sqlite3.OperationalError:
            pass
```

---

## Tests (create these files)

### `tests/test_council_protocol_v2.py`

```python
"""Tests for the vote-first council protocol."""

import pytest
from src.council.protocol import (
    aggregate_votes,
    _parse_agent_response,
    _default_response,
    apply_rate_limiters,
    PARAMETER_DEFAULTS,
    RATE_LIMITS,
)


class TestParseAgentResponse:
    def test_valid_json(self):
        raw = '{"agent": "test", "direction": "bullish", "confidence": 0.8}'
        result = _parse_agent_response(raw, "test")
        assert result["direction"] == "bullish"
        assert result["confidence"] == 0.8

    def test_json_with_code_fences(self):
        raw = '```json\n{"agent": "test", "direction": "bearish", "confidence": 0.6}\n```'
        result = _parse_agent_response(raw, "test")
        assert result["direction"] == "bearish"

    def test_invalid_json(self):
        raw = "This is not JSON at all."
        result = _parse_agent_response(raw, "test")
        assert result.get("_parse_failed") is True
        assert result["direction"] == "neutral"
        assert result["confidence"] == 0.1

    def test_missing_direction(self):
        raw = '{"agent": "test", "confidence": 0.8}'
        result = _parse_agent_response(raw, "test")
        assert result.get("_parse_failed") is True

    def test_confidence_clamped(self):
        raw = '{"agent": "test", "direction": "bullish", "confidence": 1.5}'
        result = _parse_agent_response(raw, "test")
        assert result["confidence"] == 1.0


class TestAggregateVotes:
    def test_unanimous_bullish(self):
        assessments = [
            {"agent": f"agent_{i}", "direction": "bullish", "confidence": 0.8,
             "parameters": PARAMETER_DEFAULTS.copy()}
            for i in range(5)
        ]
        result = aggregate_votes(assessments, "daily")
        assert result["direction"] == "bullish"
        assert result["consensus_reached"] is True
        assert result["consensus_type"] == "5-0"
        assert result["round2_needed"] is False

    def test_split_vote(self):
        assessments = [
            {"agent": "a1", "direction": "bullish", "confidence": 0.7, "parameters": PARAMETER_DEFAULTS.copy()},
            {"agent": "a2", "direction": "bullish", "confidence": 0.6, "parameters": PARAMETER_DEFAULTS.copy()},
            {"agent": "a3", "direction": "bearish", "confidence": 0.8, "parameters": PARAMETER_DEFAULTS.copy()},
            {"agent": "a4", "direction": "bearish", "confidence": 0.7, "parameters": PARAMETER_DEFAULTS.copy()},
            {"agent": "a5", "direction": "neutral", "confidence": 0.5, "parameters": PARAMETER_DEFAULTS.copy()},
        ]
        result = aggregate_votes(assessments, "daily")
        assert result["consensus_reached"] is False
        assert result["round2_needed"] is True

    def test_three_two_consensus(self):
        assessments = [
            {"agent": "a1", "direction": "bullish", "confidence": 0.7, "parameters": PARAMETER_DEFAULTS.copy()},
            {"agent": "a2", "direction": "bullish", "confidence": 0.6, "parameters": PARAMETER_DEFAULTS.copy()},
            {"agent": "a3", "direction": "bullish", "confidence": 0.5, "parameters": PARAMETER_DEFAULTS.copy()},
            {"agent": "a4", "direction": "bearish", "confidence": 0.8, "parameters": PARAMETER_DEFAULTS.copy()},
            {"agent": "a5", "direction": "bearish", "confidence": 0.7, "parameters": PARAMETER_DEFAULTS.copy()},
        ]
        result = aggregate_votes(assessments, "daily")
        assert result["consensus_reached"] is True
        assert "3-2" in result["consensus_type"]


class TestRateLimiters:
    def test_no_limit_needed(self):
        rec = {"position_sizing_multiplier": 0.95}
        current = {"position_sizing_multiplier": 1.0}
        result = apply_rate_limiters(rec, current)
        assert result["position_sizing_multiplier"] == 0.95
        assert result["_rate_limited"] is False

    def test_large_change_clipped(self):
        rec = {"position_sizing_multiplier": 0.25}  # 75% reduction
        current = {"position_sizing_multiplier": 1.0}
        result = apply_rate_limiters(rec, current)
        # Should be clipped to ±25% = 0.75 minimum
        assert result["position_sizing_multiplier"] == 0.75
        assert result["_rate_limited"] is True

    def test_bounds_enforced(self):
        rec = {"position_sizing_multiplier": 2.0}  # Above max 1.5
        current = {"position_sizing_multiplier": 1.5}
        result = apply_rate_limiters(rec, current)
        assert result["position_sizing_multiplier"] <= 1.5
```

---

## Summary

4 files, ~1,200 lines of new/rewritten code:
- `agents.py`: 5 agents × (system prompt + data gathering function) = ~450 lines
- `protocol.py`: vote-first protocol + aggregation + rate limiters = ~350 lines
- `value_tracker.py`: counterfactual computation + rolling summary = ~250 lines
- `engine.py`: modifications to run_session() = ~150 lines of changes
- Tests: ~120 lines across 2 test files

---

## ADDITIONAL: Debug Log Table

For full observability — the actual prompt text sent to each agent and the raw
API response before JSON parsing. Enables replaying exactly what each agent saw.

**Add to `src/council/engine.py` schema:**

```sql
CREATE TABLE IF NOT EXISTS council_debug_log (
    debug_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    round INTEGER NOT NULL,
    system_prompt_hash TEXT,
    user_message TEXT,
    raw_response TEXT,
    parsed_successfully INTEGER DEFAULT 0,
    parse_error TEXT,
    response_tokens INTEGER,
    latency_ms INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES council_sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_debug_log_session
    ON council_debug_log(session_id);
```

**In `protocol.py` `_call_claude()`**, capture timing and raw response:

```python
def _call_claude(system_prompt: str, user_message: str) -> tuple[str | None, dict]:
    """Call Claude API. Returns (raw_response, debug_info).
    
    debug_info: {"latency_ms": int, "response_tokens": int, "raw": str}
    """
    import time
    debug = {"latency_ms": 0, "response_tokens": 0, "raw": None}
    
    try:
        import anthropic
        client = anthropic.Anthropic()
        start = time.monotonic()
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        elapsed = (time.monotonic() - start) * 1000
        raw = response.content[0].text if response.content else None
        debug["latency_ms"] = int(elapsed)
        debug["response_tokens"] = response.usage.output_tokens if response.usage else 0
        debug["raw"] = raw
        return raw, debug
    except Exception as e:
        logger.error("[COUNCIL] Claude API call failed: %s", e)
        debug["raw"] = str(e)
        return None, debug
```

**In `run_round_1()`**, store debug log for each agent:

```python
    raw, debug = _call_claude(system_prompt, user_message)
    parsed = _parse_agent_response(raw, agent_name)
    
    # Store debug log
    try:
        import hashlib
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO council_debug_log "
                "(debug_id, session_id, agent_name, round, system_prompt_hash, "
                "user_message, raw_response, parsed_successfully, parse_error, "
                "response_tokens, latency_ms, created_at) "
                "VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), session_id, agent_name,
                 hashlib.md5(system_prompt.encode()).hexdigest()[:12],
                 user_message, debug.get("raw", ""),
                 0 if parsed.get("_parse_failed") else 1,
                 parsed.get("key_reasoning", "") if parsed.get("_parse_failed") else None,
                 debug.get("response_tokens", 0),
                 debug.get("latency_ms", 0),
                 datetime.now(ET).isoformat()),
            )
    except Exception as e:
        logger.warning("[COUNCIL] Debug log insert failed: %s", e)
```

Note: `run_round_1()` needs the `session_id` passed in for debug logging. Update signature:

```python
def run_round_1(
    shared_context: str,
    session_id: str | None = None,  # NEW: for debug logging
    db_path: str = "ai_research_desk.sqlite3",
) -> list[dict]:
```

---

## ADDITIONAL: Strategic / On-Demand Sessions

The council can deliberate on any business-level question — hardware purchases,
new desk proposals, scaling decisions, fund formation timing.

**In `engine.py` `run_session()`**, add `custom_question` parameter:

```python
    def run_session(
        self,
        session_type: str = "daily",
        trigger_reason: str | None = None,
        custom_question: str | None = None,  # NEW: for strategic sessions
    ) -> dict:
```

Pass through to `run_round_1()`:

```python
        round1 = run_round_1(
            shared_context,
            session_id=session_id,
            db_path=self.db_path,
            custom_question=custom_question,
        )
```

**In `protocol.py` `run_round_1()`**, use custom question if provided:

```python
def run_round_1(
    shared_context: str,
    session_id: str | None = None,
    db_path: str = "ai_research_desk.sqlite3",
    custom_question: str | None = None,  # NEW
) -> list[dict]:
    ...
    for agent_name, system_prompt in AGENT_PROMPTS.items():
        data_fn = AGENT_DATA_FUNCTIONS.get(agent_name)
        agent_data = data_fn(db_path) if data_fn else "No specialist data."

        if custom_question:
            user_message = f"""STRATEGIC QUESTION FROM FOUNDER:
{custom_question}

SHARED MARKET CONTEXT:
{shared_context}

YOUR SPECIALIST DATA:
{agent_data}

Analyze this question through your specific analytical framework.
Direction meaning: "bullish" = proceed/yes, "neutral" = wait/unclear, "bearish" = don't/no.
Produce your assessment as a JSON object. No preamble."""
        else:
            user_message = f"""SHARED MARKET CONTEXT:
{shared_context}

YOUR SPECIALIST DATA:
{agent_data}

Produce your assessment as a JSON object. No preamble, no markdown fences."""
```

**In `src/main.py`**, add CLI support:

Find the council subparser setup and add:
```python
council_parser.add_argument(
    "--question", "-q", type=str, default=None,
    help="Custom strategic question for the council (triggers strategic session)")
```

In the council command handler:
```python
    session_type = args.type if hasattr(args, 'type') else "daily"
    custom_question = getattr(args, "question", None)
    if custom_question:
        session_type = "strategic"
    
    engine = CouncilEngine()
    result = engine.run_session(
        session_type=session_type,
        trigger_reason=custom_question or f"Scheduled {session_type}",
        custom_question=custom_question,
    )
```

Usage:
```bash
python -m src.main council --question "Should we buy the RTX 3090 now or wait?"
python -m src.main council --question "Is it time to start building the mean reversion adapter?"
python -m src.main council --type weekly
```

**Telegram command** (add to `src/notifications/telegram.py`):

```python
# In the command handler section:
if text.startswith("/council "):
    question = text[len("/council "):].strip()
    if question:
        from src.council.engine import CouncilEngine
        engine = CouncilEngine()
        result = engine.run_session(
            session_type="strategic",
            trigger_reason=question,
            custom_question=question,
        )
        # Format summary for Telegram
        votes = result.get("votes", {})
        direction = votes.get("direction", "?")
        score = votes.get("aggregated_score", 0)
        consensus = votes.get("consensus_type", "?")
        cost = result.get("session_meta", {}).get("cost_usd", 0)
        
        emoji = {"bullish": "🟢", "neutral": "⚪", "bearish": "🔴"}.get(direction, "❓")
        
        summary = f"{emoji} Council: {direction.upper()} ({consensus})\n"
        summary += f"Score: {score:+.2f} | Cost: ${cost:.2f}\n\n"
        
        for a in result.get("agent_assessments", []):
            a_emoji = {"bullish": "🟢", "neutral": "⚪", "bearish": "🔴"}.get(a.get("direction"), "❓")
            summary += f"{a_emoji} {a['agent']}: {a.get('key_reasoning', '')[:80]}...\n"
        
        send_telegram(summary)
```

---

## DASHBOARD VISUAL SPEC (for Council.jsx update)

The council dashboard page should display:

**1. Current State Banner (always visible at top)**
- Traffic Light indicator (3 colored dots)
- Council direction with color (🟢 Bullish / ⚪ Neutral / 🔴 Bearish)
- Active parameter adjustments (sizing ×0.85, cash 20%, scan normal)
- Last session timestamp and cost

**2. Agent Vote Cards (5 cards in a row, main visual element)**
Each card:
- Agent name and icon at top
- Direction indicator: green/gray/red left border AND background tint
- Confidence bar (0-100% width, colored by direction)
- Key reasoning (1 paragraph, truncated with expand)
- Key risk (1 line, red text)
- Parameter recommendation chips (e.g., "sizing: 0.85", "cash: 20%")
- Dissent border: if agent disagrees with consensus, orange dashed border

**3. Consensus Badge (below cards)**
- "5-0 Unanimous ✅" / "4-1 Strong" / "3-2 Split ⚠️" / "No Consensus ❌"
- Aggregated score number
- Round indicator: "Resolved in Round 1" or "Required Round 2"
- Sycophancy flags if any (which agents flipped)

**4. Parameter Changes Table**
| Parameter | Before | Council | Applied | Rate Limited? |
|---|---|---|---|---|
| Position Sizing | 1.0 | 0.85 | 0.85 | No |

**5. Value Attribution Section**
- Rolling 30-day value added (dollars, with trend line)
- Per-agent breakdown: which agents' recommendations created/destroyed value
- Authority status badge: "Full" / "Alert (8 weeks negative)" / "Reduced"

**6. Calibration Scorecard**
- Per-agent prediction accuracy (verified predictions / total)
- Confidence calibration: are agents' stated confidences aligned with outcomes?
- Best/worst predictor highlighted

**7. Session History (expandable list)**
- Date, type, direction, consensus, cost
- Click to expand: full agent assessments, parameter changes, predictions

**8. Strategic Session Input (if applicable)**
- Text field: "Ask the council a question"
- Submit button triggers strategic session
- Results appear inline in the session history

All components use Tailwind classes matching existing dashboard dark theme.
Use Recharts for the value attribution trend line.
Use the same card/expandable pattern from existing Council.jsx.
