@echo off
echo ============================================================
echo   ARCIS WEEKLY REVIEW — %date% %time%
echo ============================================================
echo.

cd /d "%~dp0"

echo [1/5] CTO REPORT
echo ------------------------------------------------------------
python -c "from src.evaluation.cto_report import generate_cto_report; import json; print(json.dumps(generate_cto_report(days=7), indent=2, default=str))"
echo.

echo [2/5] OPEN POSITIONS
echo ------------------------------------------------------------
python -c "import sqlite3; conn = sqlite3.connect('ai_research_desk.sqlite3'); conn.row_factory = sqlite3.Row; trades = conn.execute('SELECT ticker, direction, pnl_pct, planned_allocation, actual_entry_time, strategy_type FROM shadow_trades WHERE status=\"open\" ORDER BY actual_entry_time').fetchall(); print(f'Open positions: {len(trades)}'); [print(f'  {t[\"ticker\"]:5s} {t[\"direction\"]:5s} PnL: {t[\"pnl_pct\"]:.1f}%%  Entry: {str(t[\"actual_entry_time\"])[:10]}  Strategy: {t[\"strategy_type\"] or \"pullback\"}') if t['pnl_pct'] else print(f'  {t[\"ticker\"]:5s} {t[\"direction\"]:5s} PnL: N/A      Entry: {str(t[\"actual_entry_time\"])[:10]}  Strategy: {t[\"strategy_type\"] or \"pullback\"}') for t in trades]; closed = conn.execute('SELECT COUNT(*) FROM shadow_trades WHERE status=\"closed\"').fetchone()[0]; print(f'\nClosed trades: {closed}')"
echo.

echo [3/5] RECENT SCANS
echo ------------------------------------------------------------
python -c "import sqlite3; conn = sqlite3.connect('ai_research_desk.sqlite3'); rows = conn.execute('SELECT scan_time, packet_worthy, llm_success, llm_total, avg_conviction FROM scan_metrics ORDER BY created_at DESC LIMIT 20').fetchall(); print(f'  {\"Time\":>8s} {\"Packets\":>8s} {\"LLM_OK\":>7s} {\"LLM_Tot\":>8s} {\"AvgConv\":>8s}'); [print(f'  {str(r[0]):>8s} {r[1] or 0:>8d} {r[2] or 0:>7d} {r[3] or 0:>8d} {r[4] or 0:>8.1f}') for r in rows]"
echo.

echo [4/5] TRAINING DATA
echo ------------------------------------------------------------
python -c "import sqlite3; conn = sqlite3.connect('ai_research_desk.sqlite3'); total = conn.execute('SELECT COUNT(*) FROM training_examples').fetchone()[0]; recent = conn.execute('SELECT COUNT(*) FROM training_examples WHERE created_at > datetime(\"now\", \"-7 days\")').fetchone()[0]; scored = conn.execute('SELECT COUNT(*), AVG(quality_score) FROM training_examples WHERE quality_score IS NOT NULL').fetchone(); print(f'Training examples: {total} total, {recent} this week'); print(f'Scored: {scored[0]}, avg quality: {scored[1]:.2f}' if scored[1] else f'Scored: {scored[0]}, avg quality: N/A')"
echo.

echo [5/5] TRAFFIC LIGHT + VIX
echo ------------------------------------------------------------
python -c "import sqlite3; conn = sqlite3.connect('ai_research_desk.sqlite3'); tl = conn.execute('SELECT current_regime, last_total_score FROM traffic_light_state WHERE id=1').fetchone(); vix = conn.execute('SELECT vix, collected_date FROM vix_term_structure ORDER BY collected_date DESC LIMIT 1').fetchone(); print(f'Traffic Light: {tl[0]} (score {tl[1]})' if tl else 'Traffic Light: no data'); print(f'VIX: {vix[0]:.1f} (as of {vix[1]})' if vix else 'VIX: no data')"
echo.

echo ============================================================
echo   REVIEW COMPLETE — Copy everything above and paste to Claude
echo ============================================================
pause
