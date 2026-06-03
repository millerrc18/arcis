"""Assistant postmortem generation for closed shadow trades.

Called by: shadow_trading.executor
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_postmortem.py
"""


def generate_postmortem(trade: dict, features_at_entry: dict | None = None) -> str:
    """Generate a structured postmortem analysis for a closed shadow trade.

    Args:
        trade: Closed shadow trade dict (or recommendation dict with shadow fields).
        features_at_entry: Optional features snapshot from entry time.

    Returns:
        Plain-text postmortem string.
    """
    ticker = trade.get("ticker", "???")
    exit_reason = trade.get("exit_reason", "unknown")

    entry_price = trade.get("actual_entry_price") or trade.get("shadow_entry_price") or trade.get("entry_price", 0)
    exit_price = trade.get("actual_exit_price") or trade.get("shadow_exit_price", 0)
    pnl = trade.get("pnl_dollars") or trade.get("shadow_pnl_dollars", 0) or 0
    pnl_pct = trade.get("pnl_pct") or trade.get("shadow_pnl_pct", 0) or 0
    duration = trade.get("duration_days") or trade.get("shadow_duration_days", 0) or 0
    mfe = trade.get("max_favorable_excursion", 0) or 0
    mae = trade.get("max_adverse_excursion", 0) or 0
    stop_price = trade.get("stop_price") or 0
    target_1 = trade.get("target_1") or 0
    target_2 = trade.get("target_2") or 0

    # PG-cutover hardening (#132): psycopg2 returns timestamp columns as native
    # datetime objects (connect_db's RealDictCursor does NOT stringify), so the
    # SQLite-era `[:10]` slice raised "'datetime.datetime' object is not
    # subscriptable" — aborting check_and_manage_open_trades mid-close and
    # leaving the broker position open ("close-didn't-clear" → orphan source).
    # str()-coerce first: str(datetime)[:10] and str(iso_string)[:10] both yield
    # the YYYY-MM-DD date prefix.
    entry_date = str(trade.get("actual_entry_time") or trade.get("shadow_entry_time") or "")[:10]
    exit_date = str(trade.get("actual_exit_time") or trade.get("shadow_exit_time") or "")[:10]

    thesis_text = trade.get("thesis_text", "")
    atr = trade.get("atr", 0) or 0

    # Determine what went right/wrong
    went_right = []
    went_wrong = []
    thesis_outcome = "Inconclusive"
    lessons = []

    if pnl > 0:
        # Winning trade
        if exit_reason in ("target_1_hit", "target_2_hit"):
            thesis_outcome = "Validated"
            went_right.append("Trend thesis was correct, price moved favorably to target")
            if exit_reason == "target_1_hit" and target_2 > 0 and mfe > (target_1 - entry_price if isinstance(target_1, (int, float)) and isinstance(entry_price, (int, float)) else 0):
                went_wrong.append("Price continued past T1 after exit — left money on the table")
                lessons.append("Consider trailing stop or partial exit at T1")
            else:
                lessons.append("Setup worked as designed — repeatable pattern")
        elif exit_reason == "timeout":
            thesis_outcome = "Partially validated (slow)"
            went_right.append("Directionally correct — MFE was positive")
            went_wrong.append("Thesis was too slow to develop within timeout window")
            lessons.append("Consider extending hold period for this setup type")
        elif exit_reason == "manual":
            thesis_outcome = "Validated (manual exit)"
            went_right.append("Trade was profitable at manual exit")
        else:
            went_right.append("Trade closed with positive P&L")
    else:
        # Losing trade
        if exit_reason == "stop_hit":
            thesis_outcome = "Invalidated"
            if stop_price > 0 and entry_price > 0:
                stop_distance = entry_price - stop_price
                if atr > 0 and stop_distance < atr:
                    went_wrong.append("Stop was tight relative to ATR — may have been shaken out")
                    lessons.append("Consider wider stop (2x ATR minimum) for this volatility level")
                else:
                    went_wrong.append("Price moved against thesis and hit stop — thesis was wrong")
                    lessons.append("Review entry timing and thesis quality for this setup")
            else:
                went_wrong.append("Stop hit — thesis invalidated")
                lessons.append("Review setup selection criteria")

            if mfe > 0:
                went_right.append(f"Trade showed favorable movement (MFE ${mfe:+.2f}) before reversing")
        elif exit_reason == "timeout":
            thesis_outcome = "Inconclusive"
            if mfe > 0:
                went_right.append("Some favorable movement during hold period")
                went_wrong.append("Insufficient momentum to reach targets within timeout")
                lessons.append("Setup lacked catalyst or momentum — consider timing entry better")
            else:
                went_wrong.append("Trade went nowhere or negative throughout hold period")
                lessons.append("Thesis was weak from the start — raise qualification bar")
        elif exit_reason == "manual":
            went_wrong.append("Manually closed at a loss")
            lessons.append("Review reason for manual close")
        else:
            went_wrong.append(f"Trade closed with negative P&L ({exit_reason})")

    # MFE/MAE analysis
    if mfe > 0 and pnl > 0 and mfe > pnl:
        went_wrong.append(f"Left ${mfe - pnl:.2f} on the table (MFE was ${mfe:+.2f} vs realized ${pnl:+.2f})")
    if mae < 0 and pnl > 0 and abs(mae) > abs(pnl):
        went_right.append(f"Survived deep drawdown (MAE ${mae:+.2f}) to finish profitable")

    # Repeatability
    if pnl > 0 and exit_reason in ("target_1_hit", "target_2_hit"):
        repeatability = "Would take this setup again"
    elif pnl > 0:
        repeatability = "Profitable but needs refinement"
    elif exit_reason == "stop_hit" and mfe > 0:
        repeatability = "Needs refinement — directionally correct but stopped out"
    elif exit_reason == "timeout" and mfe > 0:
        repeatability = "Needs refinement — correct but too slow"
    else:
        repeatability = "Would pass next time"

    if not went_right:
        went_right.append("No clear positives identified")
    if not went_wrong:
        went_wrong.append("No clear negatives identified")
    if not lessons:
        lessons.append("Monitor similar setups for pattern confirmation")

    # Format
    right_text = "\n".join(f"  - {item}" for item in went_right)
    wrong_text = "\n".join(f"  - {item}" for item in went_wrong)
    lesson_text = "\n".join(f"  - {item}" for item in lessons)

    postmortem = f"""POSTMORTEM — {ticker} ({exit_reason})
{'='*50}

Trade Summary:
  Entry: ${entry_price:.2f} on {entry_date}
  Exit:  ${exit_price:.2f} on {exit_date} ({exit_reason})
  P&L:   ${pnl:+.2f} ({pnl_pct:+.1f}%)
  Duration: {duration} days
  MFE: ${mfe:+.2f} | MAE: ${mae:+.2f}

What went right:
{right_text}

What went wrong:
{wrong_text}

Thesis evaluation:
  - Original thesis: {(thesis_text[:200] + '...') if thesis_text and len(thesis_text) > 200 else thesis_text or 'n/a'}
  - Outcome: {thesis_outcome}

Lessons:
{lesson_text}

Repeatability: {repeatability}"""

    return postmortem


def determine_lesson_tag(trade: dict) -> str:
    """Determine a lesson tag based on trade outcome.

    Returns a tag string like 'thesis_validated', 'thesis_invalidated', etc.
    """
    exit_reason = trade.get("exit_reason", "unknown")
    # float() casts: same #195 SQLite TEXT-for-REAL pattern as generate_postmortem
    pnl = float(trade.get("pnl_dollars") or trade.get("shadow_pnl_dollars") or 0)
    mfe = float(trade.get("max_favorable_excursion") or 0)
    entry_price = float(trade.get("actual_entry_price") or trade.get("entry_price") or 0)
    target_1 = float(trade.get("target_1") or 0)

    if exit_reason in ("target_1_hit", "target_2_hit"):
        # Check if MFE was much larger than realized gain (left money on table)
        if mfe > 0 and pnl > 0 and mfe > pnl * 1.5:
            return "early_exit"
        return "thesis_validated"

    if exit_reason == "stop_hit":
        mae = float(trade.get("max_adverse_excursion") or 0)
        stop_price = float(trade.get("stop_price") or 0)
        stop_distance = entry_price - stop_price if entry_price and stop_price else 0
        # If MAE was much larger than stop distance but trade survived
        if mfe > 0 and abs(mae) > stop_distance * 0.8:
            return "volatile_but_correct"
        return "thesis_invalidated"

    if exit_reason == "timeout":
        return "thesis_inconclusive"

    if exit_reason == "manual":
        return "manual_close"

    return "unknown"
