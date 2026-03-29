"""AI Council agent definitions — vote-first protocol.

Five analytical lenses, each producing structured JSON.
Research: AI_Council_Redesign_v2__Architecture_and_Implementation.md

Agents:
  tactical_operator   — Market microstructure, short-term price action
  strategic_architect  — Portfolio theory, Kelly, phase gates
  red_team             — Adversarial pre-mortem, tail risk
  innovation_engine    — R&D pipeline, ML experiments
  macro_navigator      — Macro-financial, regulatory, structural

FIX #7:  _query_db helper preserved from original agents.py
FIX #9:  Red Team prompt uses independent data analysis for Round 1
FIX #11: gather functions accept session_type for future per-type depth
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


# ── Shared helper (FIX #7: preserved from original agents.py) ────

def _query_db(query: str, params: tuple = (), db_path: str = DB_PATH) -> list[dict]:
    """Execute a read query and return rows as list of dicts."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


# ── JSON output schema (appended to every agent prompt) ──────────

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


# ══════════════════════════════════════════════════════════════════
# AGENT SYSTEM PROMPTS
# ══════════════════════════════════════════════════════════════════

TACTICAL_OPERATOR_PROMPT = f"""\
You are the Tactical Operator on a five-member AI trading council for Halcyon Lab,
an autonomous equity pullback trading system on S&P 100 stocks.

ANALYTICAL FRAMEWORK:
- Market microstructure analysis: volume patterns, spread dynamics, order flow
- Regime detection: classify conditions using VIX, credit spreads, trend indicators
- Short-term price action: momentum and mean reversion signals over 1-5 day horizons
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
- Phase gate evaluation: are we on track for the 50-trade gate? 100-trade gate?
- Resource allocation: where should development effort be focused?

CORE QUESTION: "Are we on track, and how should we allocate capital and attention?"

EVALUATION CRITERIA:
1. How many closed trades vs the 50-trade Phase 1 gate? Expected timeline?
2. Is the system health score (HSHS) improving or degrading?
3. Are we building the data asset fast enough? (training data growth rate)
4. Is the training pipeline healthy? (retrain frequency, quality scores, fallback rate)
5. Should we hold capital in reserve for better opportunities, or deploy more?

{AGENT_OUTPUT_SCHEMA}
"""

RED_TEAM_PROMPT = f"""\
You are the Red Team analyst on a five-member AI trading council for Halcyon Lab.
Your SOLE purpose is adversarial analysis. You are paid to find problems.

ANALYTICAL FRAMEWORK:
- Pre-mortem: assume the system fails in the next 30 days — what caused it?
- Tail risk: what is the worst 2-sigma event for the current portfolio?
- Model degradation: is the LLM producing worse analysis over time?
- Concentration risk: are positions correlated in ways we haven't measured?
- Competitive threats: are other traders crowding our signals?

CORE QUESTION: "What are we missing, and what kills us?"

EVALUATION CRITERIA:
1. What is the maximum portfolio loss if all positions move against us simultaneously?
2. Is drawdown trajectory concerning? (accelerating, decelerating, stable)
3. Are sector concentrations within safe limits even under stress?
4. Is the model's template fallback rate increasing? (sign of degradation)
5. What external event (Fed, earnings, geopolitical) could overwhelm our bracket stops?

BIAS: You are ALWAYS skeptical. When uncertain, lean bearish. Your value comes
from identifying risks others overlook, not from agreeing with the consensus.
Base your analysis on the DATA provided, not on what other agents might think.

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


# ══════════════════════════════════════════════════════════════════
# DATA GATHERING FUNCTIONS
# ══════════════════════════════════════════════════════════════════
# Each returns a formatted STRING (not dict). LLMs process natural
# text better than raw JSON with escapes and nulls.
# Every query is wrapped in try/except — never crashes.


def gather_tactical_data(db_path: str = DB_PATH) -> str:
    """Gather market microstructure and short-term data for Tactical Operator."""
    parts = []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            # VIX and term structure
            try:
                vix = conn.execute(
                    "SELECT vix, vix9d, vix3m FROM vix_term_structure "
                    "ORDER BY collected_date DESC LIMIT 1"
                ).fetchone()
                if vix:
                    parts.append(f"VIX: {vix['vix']:.1f} | VIX9D: {vix['vix9d']:.1f} | VIX3M: {vix['vix3m']:.1f}")
                    if vix['vix'] and vix['vix3m']:
                        structure = "contango (complacency)" if vix['vix'] < vix['vix3m'] else "backwardation (fear)"
                        parts.append(f"Term structure: {structure}")
            except Exception as e:
                logger.debug("[COUNCIL] Tactical VIX query: %s", e)

            # Traffic Light
            try:
                tl = conn.execute(
                    "SELECT current_regime, last_total_score FROM traffic_light_state WHERE id = 1"
                ).fetchone()
                if tl:
                    parts.append(f"Traffic Light: {tl['current_regime']} (score {tl['last_total_score']}/6)")
            except Exception:
                pass

            # Recent scan results
            try:
                scans = conn.execute(
                    "SELECT scan_time, packet_worthy, llm_success, llm_total, avg_conviction "
                    "FROM scan_metrics ORDER BY created_at DESC LIMIT 5"
                ).fetchall()
                if scans:
                    parts.append("\nRecent scans:")
                    for s in scans:
                        fb = ""
                        if s['llm_total'] and s['llm_total'] > 0:
                            fb = f" fallback={((s['llm_total'] - (s['llm_success'] or 0)) / s['llm_total'] * 100):.0f}%"
                        parts.append(f"  {s['scan_time']}: {s['packet_worthy']} packets, "
                                     f"conv {s['avg_conviction']:.1f}{fb}")
            except Exception as e:
                logger.debug("[COUNCIL] Tactical scan query: %s", e)

            # Open positions with P&L
            try:
                positions = conn.execute(
                    "SELECT st.ticker, st.pnl_pct, r.sector_context as sector, "
                    "CAST(julianday('now') - julianday(actual_entry_time) AS INTEGER) as days "
                    "FROM shadow_trades st "
                    "LEFT JOIN recommendations r ON st.recommendation_id = r.recommendation_id "
                    "WHERE st.status = 'open' ORDER BY st.pnl_pct DESC"
                ).fetchall()
                if positions:
                    winners = sum(1 for p in positions if (p['pnl_pct'] or 0) > 0)
                    total_pnl = sum(p['pnl_pct'] or 0 for p in positions)
                    parts.append(f"\nOpen positions ({len(positions)}): {winners} green, "
                                 f"{len(positions) - winners} red, aggregate {total_pnl:+.1f}%")
                    for p in positions[:8]:
                        e = "📈" if (p['pnl_pct'] or 0) > 0 else "📉"
                        parts.append(f"  {e} {p['ticker']} ({p['sector'] or '?'}): "
                                     f"{(p['pnl_pct'] or 0):+.1f}% ({p['days'] or 0}d)")
                else:
                    parts.append("\nNo open positions.")
            except Exception as e:
                logger.debug("[COUNCIL] Tactical positions query: %s", e)

    except Exception as e:
        logger.warning("[COUNCIL] Tactical data gather failed: %s", e)

    return "\n".join(parts) if parts else "No tactical data available."


def gather_strategic_data(db_path: str = DB_PATH) -> str:
    """Gather portfolio strategy and phase gate data for Strategic Architect."""
    parts = []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Trade count vs gates
            try:
                closed = conn.execute("SELECT COUNT(*) as n FROM shadow_trades WHERE status = 'closed'").fetchone()
                total = conn.execute("SELECT COUNT(*) as n FROM shadow_trades").fetchone()
                n_closed = closed['n'] if closed else 0
                n_open = (total['n'] if total else 0) - n_closed
                parts.append(f"Trades: {n_closed} closed, {n_open} open")
                parts.append(f"Phase 1 gate: {n_closed}/50 ({n_closed / 50 * 100:.0f}%)")
            except Exception as e:
                logger.debug("[COUNCIL] Strategic trade count: %s", e)

            # P&L summary
            try:
                pnl = conn.execute(
                    "SELECT SUM(pnl_dollars) as total, AVG(pnl_pct) as avg, "
                    "COUNT(CASE WHEN pnl_dollars > 0 THEN 1 END) as wins, COUNT(*) as n "
                    "FROM shadow_trades WHERE status = 'closed' AND pnl_dollars IS NOT NULL"
                ).fetchone()
                if pnl and pnl['n'] > 0:
                    wr = pnl['wins'] / pnl['n'] * 100
                    parts.append(f"P&L: ${pnl['total']:.2f} total, {pnl['avg']:.2f}% avg, "
                                 f"{wr:.0f}% WR ({pnl['wins']}/{pnl['n']})")
            except Exception as e:
                logger.debug("[COUNCIL] Strategic P&L: %s", e)

            # Training data
            try:
                td = conn.execute(
                    "SELECT COUNT(*) as n, AVG(quality_score) as q "
                    "FROM training_examples"
                ).fetchone()
                if td:
                    q_str = f", avg quality {td['q']:.1f}" if td['q'] else ", no quality scores"
                    parts.append(f"\nTraining: {td['n']} examples{q_str}")
            except Exception:
                pass

            # HSHS
            try:
                from src.evaluation.hshs_live import compute_hshs
                h = compute_hshs(db_path)
                parts.append(f"HSHS: {h.get('hshs', 0):.1f}/100 (phase: {h.get('phase', '?')})")
                for dim, val in h.get("dimensions", {}).items():
                    parts.append(f"  {dim}: {val:.0f}")
            except Exception:
                pass

            # Model versions
            try:
                v = conn.execute("SELECT COUNT(*) as n FROM model_versions").fetchone()
                if v:
                    parts.append(f"Model versions trained: {v['n']}")
            except Exception:
                pass

    except Exception as e:
        logger.warning("[COUNCIL] Strategic data gather failed: %s", e)

    return "\n".join(parts) if parts else "No strategic data available."


def gather_risk_data(db_path: str = DB_PATH) -> str:
    """Gather risk and concentration data for Red Team."""
    parts = []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Sector concentration
            try:
                sectors = conn.execute(
                    "SELECT r.sector_context as sector, COUNT(*) as n, SUM(st.planned_allocation) as alloc "
                    "FROM shadow_trades st "
                    "LEFT JOIN recommendations r ON st.recommendation_id = r.recommendation_id "
                    "WHERE st.status = 'open' AND r.sector_context IS NOT NULL "
                    "GROUP BY r.sector_context ORDER BY n DESC"
                ).fetchall()
                if sectors:
                    parts.append("Sector concentration (open):")
                    for s in sectors:
                        alloc = f" (${s['alloc']:.0f})" if s['alloc'] else ""
                        parts.append(f"  {s['sector']}: {s['n']} positions{alloc}")
                else:
                    parts.append("No open positions for sector analysis.")
            except Exception as e:
                logger.debug("[COUNCIL] Risk sector: %s", e)

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
                        parts.append(f"  {l['ticker']}: {l['pnl_pct']:.1f}% "
                                     f"({l['exit_reason']}) {(l['actual_exit_time'] or '')[:10]}")
            except Exception as e:
                logger.debug("[COUNCIL] Risk losses: %s", e)

            # Template fallback rate (model health)
            try:
                fb = conn.execute(
                    "SELECT SUM(llm_success) as ok, SUM(llm_total) as total "
                    "FROM scan_metrics WHERE created_at > datetime('now', '-7 days')"
                ).fetchone()
                if fb and fb['total'] and fb['total'] > 0:
                    rate = (1 - fb['ok'] / fb['total']) * 100
                    status = "⚠️ ELEVATED" if rate > 20 else "✓ normal"
                    parts.append(f"\n7-day fallback rate: {rate:.1f}% ({status})")
            except Exception:
                pass

            # Cumulative P&L for drawdown context
            try:
                cum = conn.execute(
                    "SELECT SUM(pnl_dollars) as total FROM shadow_trades WHERE status = 'closed'"
                ).fetchone()
                if cum and cum['total'] is not None:
                    parts.append(f"Cumulative closed P&L: ${cum['total']:.2f}")
            except Exception:
                pass

            # Max adverse excursion (worst intra-trade drawdown)
            try:
                mae = conn.execute(
                    "SELECT ticker, MIN(max_adverse_excursion) as worst_mae "
                    "FROM shadow_trades WHERE status = 'closed' AND max_adverse_excursion IS NOT NULL"
                ).fetchone()
                if mae and mae['worst_mae'] is not None:
                    parts.append(f"Worst MAE (single trade): {mae['worst_mae']:.1f}%")
            except Exception:
                pass

    except Exception as e:
        logger.warning("[COUNCIL] Risk data gather failed: %s", e)

    return "\n".join(parts) if parts else "No risk data available."


def gather_innovation_data(db_path: str = DB_PATH) -> str:
    """Gather ML pipeline and training data for Innovation Engine."""
    parts = []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            now = datetime.now(ET)
            week_ago = (now - timedelta(days=7)).isoformat()
            month_ago = (now - timedelta(days=30)).isoformat()

            # Training data trends
            try:
                total = conn.execute("SELECT COUNT(*) as n FROM training_examples").fetchone()
                new_wk = conn.execute(
                    "SELECT COUNT(*) as n FROM training_examples WHERE created_at > ?", (week_ago,)
                ).fetchone()
                new_mo = conn.execute(
                    "SELECT COUNT(*) as n FROM training_examples WHERE created_at > ?", (month_ago,)
                ).fetchone()
                parts.append(f"Training data: {total['n']} total, "
                             f"+{new_wk['n']} this week, +{new_mo['n']} this month")
            except Exception:
                pass

            # Quality scores
            try:
                q = conn.execute(
                    "SELECT AVG(quality_score) as avg, MIN(quality_score) as min, "
                    "MAX(quality_score) as max, "
                    "COUNT(CASE WHEN quality_score IS NULL OR quality_score = 0 THEN 1 END) as unscored "
                    "FROM training_examples"
                ).fetchone()
                if q:
                    parts.append(f"Quality: avg={q['avg']:.1f}, range [{q['min']:.0f}-{q['max']:.0f}], "
                                 f"{q['unscored']} unscored" if q['avg'] else f"Quality: {q['unscored']} unscored")
            except Exception:
                pass

            # Source distribution
            try:
                sources = conn.execute(
                    "SELECT source, COUNT(*) as n FROM training_examples "
                    "GROUP BY source ORDER BY n DESC"
                ).fetchall()
                if sources:
                    parts.append("\nSources:")
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
                    parts.append("Curriculum:")
                    for s in stages:
                        parts.append(f"  {s['curriculum_stage']}: {s['n']}")
            except Exception:
                pass

            # Fallback rate trend
            try:
                fb = conn.execute(
                    "SELECT DATE(created_at) as day, "
                    "CAST(SUM(llm_total - COALESCE(llm_success, 0)) AS FLOAT) / "
                    "NULLIF(SUM(llm_total), 0) * 100 as fb_pct "
                    "FROM scan_metrics WHERE llm_total > 0 "
                    "GROUP BY DATE(created_at) ORDER BY day DESC LIMIT 7"
                ).fetchall()
                if fb:
                    parts.append("\nFallback rate (7 days):")
                    for f in fb:
                        parts.append(f"  {f['day']}: {f['fb_pct']:.1f}%")
            except Exception:
                pass

    except Exception as e:
        logger.warning("[COUNCIL] Innovation data gather failed: %s", e)

    return "\n".join(parts) if parts else "No innovation data available."


def gather_macro_data(db_path: str = DB_PATH) -> str:
    """Gather macroeconomic and regime data for Macro Navigator."""
    parts = []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Key macro indicators
            try:
                indicators = [
                    ("DFF", "Fed Funds Rate"),
                    ("T10Y2Y", "10Y-2Y Spread"),
                    ("T10Y3M", "10Y-3M Spread"),
                    ("BAMLH0A0HYM2", "HY Spread (OAS)"),
                    ("UNRATE", "Unemployment"),
                ]
                lines = []
                for sid, label in indicators:
                    row = conn.execute(
                        "SELECT value, collected_date FROM macro_snapshots "
                        "WHERE series_id = ? ORDER BY collected_date DESC LIMIT 1", (sid,)
                    ).fetchone()
                    if row:
                        lines.append(f"  {label}: {row['value']:.2f} ({row['collected_date']})")
                if lines:
                    parts.append("Macro indicators:")
                    parts.extend(lines)
            except Exception as e:
                logger.debug("[COUNCIL] Macro indicators: %s", e)

            # Yield curve
            try:
                spread = conn.execute(
                    "SELECT value FROM macro_snapshots "
                    "WHERE series_id = 'T10Y2Y' ORDER BY collected_date DESC LIMIT 1"
                ).fetchone()
                if spread:
                    v = spread['value']
                    if v < 0:
                        parts.append(f"\n⚠️ Yield curve INVERTED ({v:.2f}%)")
                    elif v < 0.5:
                        parts.append(f"\nYield curve flat ({v:.2f}%)")
                    else:
                        parts.append(f"\nYield curve normal ({v:.2f}%)")
            except Exception:
                pass

            # Credit conditions
            try:
                hy = conn.execute(
                    "SELECT value FROM macro_snapshots "
                    "WHERE series_id = 'BAMLH0A0HYM2' ORDER BY collected_date DESC LIMIT 1"
                ).fetchone()
                hy_avg = conn.execute(
                    "SELECT AVG(value) as avg FROM macro_snapshots "
                    "WHERE series_id = 'BAMLH0A0HYM2' AND collected_date > date('now', '-365 days')"
                ).fetchone()
                if hy and hy_avg and hy_avg['avg']:
                    z = (hy['value'] - hy_avg['avg']) / max(0.1, abs(hy_avg['avg'] * 0.15))
                    status = "tight" if z < 0 else "normal" if z < 1 else "widening" if z < 2 else "STRESS"
                    parts.append(f"Credit: {status} (HY OAS z ≈ {z:.1f})")
            except Exception:
                pass

            # Sector performance from closed trades
            try:
                sp = conn.execute(
                    "SELECT r.sector_context as sector, AVG(st.pnl_pct) as avg, COUNT(*) as n "
                    "FROM shadow_trades st "
                    "LEFT JOIN recommendations r ON st.recommendation_id = r.recommendation_id "
                    "WHERE st.status = 'closed' AND r.sector_context IS NOT NULL "
                    "GROUP BY r.sector_context HAVING n >= 2 ORDER BY avg DESC"
                ).fetchall()
                if sp:
                    parts.append("\nSector performance (closed trades):")
                    for s in sp:
                        e = "🟢" if s['avg'] > 0 else "🔴"
                        parts.append(f"  {e} {s['sector']}: {s['avg']:+.1f}% ({s['n']})")
            except Exception:
                pass

    except Exception as e:
        logger.warning("[COUNCIL] Macro data gather failed: %s", e)

    return "\n".join(parts) if parts else "No macro data available."


# ── Agent-to-function mapping ─────────────────────────────────────
# All 5 agents run in Round 1 (no special-casing like old devils_advocate)

AGENT_DATA_FUNCTIONS = {
    "tactical_operator": gather_tactical_data,
    "strategic_architect": gather_strategic_data,
    "red_team": gather_risk_data,
    "innovation_engine": gather_innovation_data,
    "macro_navigator": gather_macro_data,
}
