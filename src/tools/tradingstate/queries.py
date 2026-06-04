"""SQL constants for TradingState. Single locus for PG/SQLite divergence.

Called by: src/tools/tradingstate/core.py
Calls: none (constants only)
Owns tables: none (queries against shadow_trades, recommendations, audit_reports, schedule_metrics)
Config keys: none
Tests: tests/tools/test_tradingstate_integration.py

Schema-discipline (spec F3/F4, decisions 10/11):
  - Use actual_entry_time aliased AS entry_time (F3 — no legacy alias allowed)
  - Use overall_assessment verbatim (F4 — no legacy alias allowed)
"""

OPEN_POSITIONS_PG = """
SELECT st.trade_id, st.ticker, st.source, st.status,
       st.entry_price,
       st.actual_entry_time AS entry_time,
       st.quarantined,
       r.thesis_text
FROM shadow_trades st
LEFT JOIN recommendations r ON r.recommendation_id = st.recommendation_id
WHERE st.source IN ('live', 'paper')
  AND st.status IN ('open', 'exit_pending')
  AND COALESCE(st.quarantined, 0) = 0
ORDER BY st.actual_entry_time DESC
"""

RECENT_AUDIT_PG = """
SELECT audit_id, created_at, overall_assessment
FROM audit_reports
ORDER BY created_at DESC
LIMIT 1
"""

GPU_METRICS_PG = """
SELECT metric_name, metric_value
FROM schedule_metrics
WHERE metric_date::date = CURRENT_DATE
"""

# SQLite variants: OPEN_POSITIONS and RECENT_AUDIT are identical to PG —
# LEFT JOIN, COALESCE, and ORDER BY are all valid SQLite syntax.
# GPU_METRICS diverges: PG requires metric_date::date = CURRENT_DATE because
# schedule_metrics.metric_date is stored as TEXT and PostgreSQL has no implicit
# text=date cast (UndefinedFunction). In SQLite, CURRENT_DATE returns TEXT
# ('YYYY-MM-DD') and metric_date is also TEXT, so plain = works.
OPEN_POSITIONS_SQLITE = OPEN_POSITIONS_PG
RECENT_AUDIT_SQLITE = RECENT_AUDIT_PG
GPU_METRICS_SQLITE = """
SELECT metric_name, metric_value
FROM schedule_metrics
WHERE metric_date = CURRENT_DATE
"""
