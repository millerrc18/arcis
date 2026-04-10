"""Telegram bot command handler for Arcis.

Contains the long-polling command loop, action reminder checks, the
command router, and all /cmd_* handler functions.  Extracted from
src.notifications.telegram to keep that module focused on outbound
notifications.

Functions:
    poll_commands        — long-poll Telegram getUpdates for bot commands
    check_action_reminders — daily operator-action reminder checks
    handle_command       — route an incoming command string to its handler
    _cmd_status … _cmd_heartbeat — individual command implementations
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from src.config import DB_PATH, load_config
from src.notifications.telegram import send_telegram, is_telegram_enabled

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

TELEGRAM_UPDATES_API = "https://api.telegram.org/bot{token}/getUpdates"


def _get_telegram_config() -> dict:
    """Load Telegram config from settings. .env takes precedence over YAML.

    Environment variables override YAML so that Render can set tokens via
    env vars without touching the config file.
    """
    import os
    config = load_config()
    tg = config.get("telegram", {})
    return {
        "enabled": tg.get("enabled", False),
        "bot_token": os.environ.get("TELEGRAM_BOT_TOKEN") or tg.get("bot_token", ""),
        "chat_id": os.environ.get("TELEGRAM_CHAT_ID") or str(tg.get("chat_id", "")),
    }


def poll_commands(last_update_id: int = 0) -> tuple[list[dict], int]:
    """Poll for incoming Telegram commands.

    Returns (commands, new_last_update_id).
    Each command is {"command": "/status", "args": "", "chat_id": "123"}.

    Security: Only processes commands from the authorized chat_id configured
    in settings. Commands from other chats are silently ignored. The @botname
    suffix is stripped so /status@ArcisBot and /status both work.
    """
    cfg = _get_telegram_config()
    if not cfg["enabled"] or not cfg["bot_token"]:
        return [], last_update_id

    try:
        url = TELEGRAM_UPDATES_API.format(token=cfg["bot_token"])
        resp = requests.get(
            url,
            params={"offset": last_update_id + 1, "timeout": 1},
            timeout=5,
        )
        if resp.status_code != 200:
            return [], last_update_id

        data = resp.json()
        if not data.get("ok") or not data.get("result"):
            return [], last_update_id

        commands = []
        new_id = last_update_id
        for update in data["result"]:
            new_id = max(new_id, update["update_id"])
            msg = update.get("message", {})
            text = msg.get("text", "")
            chat_id = str(msg.get("chat", {}).get("id", ""))

            # Only process commands from our authorized chat
            if chat_id != cfg["chat_id"]:
                continue

            if text.startswith("/"):
                parts = text.split(maxsplit=1)
                cmd = parts[0].lower().split("@")[0]  # Strip @botname
                args = parts[1] if len(parts) > 1 else ""
                commands.append({"command": cmd, "args": args, "chat_id": chat_id})

        return commands, new_id

    except Exception as e:
        logger.debug("[TELEGRAM] Poll error: %s", e)
        return [], last_update_id


def check_action_reminders(db_path: str = DB_PATH) -> list[str]:
    """Check all conditions that require manual action. Returns list of actions sent.

    Called daily at 8 PM from the watch loop. The system is designed to be
    autonomous, but some actions genuinely require the operator (phase gate
    review, API key rotation). This function checks each condition and sends
    a Telegram notification with specific CLI commands to run.

    Checks (in order):
    1. Phase gate milestone reached (50/100/200 closed trades)
    2. Sunday review ritual reminder (Sundays at 5 PM)
    3. API key rotation (every 90 days)
    4. Unscored training examples accumulating (>100 backlog)
    5. Saturday retrain overdue (>14 days since last model)
    """
    import sqlite3
    from src.notifications.telegram import notify_action_required
    sent = []
    now = datetime.now(ET)

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            # 1. Phase gate milestones
            closed = conn.execute(
                "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed'"
                " AND COALESCE(quarantined, 0) = 0"
            ).fetchone()
            closed_count = closed["c"] if closed else 0

            for milestone in [50, 100, 200, 500]:
                if closed_count >= milestone:
                    # Check if we already notified for this milestone
                    already = conn.execute(
                        "SELECT COUNT(*) as c FROM activity_log "
                        "WHERE event_type = 'gate_milestone' AND detail LIKE ?",
                        (f"%{milestone}%",),
                    ).fetchone()
                    if not (already and already["c"] > 0):
                        notify_action_required(
                            f"Phase gate: {milestone} closed trades reached!",
                            f"You have {closed_count} closed trades.\n"
                            f"Run: <code>python -m src.main evaluate-gate</code>\n"
                            f"Then review results with Claude.",
                            urgency="high",
                        )
                        try:
                            conn.execute(
                                "INSERT INTO activity_log (event_type, detail, created_at) "
                                "VALUES (?, ?, ?)",
                                ("gate_milestone", f"Notified {milestone} trades", now.isoformat()),
                            )
                            conn.commit()
                        except Exception as e:
                            logger.warning("[TELEGRAM] gate_milestone activity_log insert failed: %s", e)
                        sent.append(f"gate_{milestone}")
                    break  # Only notify for highest milestone

            # 2. Sunday review ritual (5 PM Sundays)
            if now.weekday() == 6 and now.hour == 17:
                notify_action_required(
                    "Weekly review ritual",
                    "Export 20 recent training examples + arcis.log + dashboard screenshots.\n"
                    "Review with Claude for format drift, look-ahead bias, regime gaps.\n"
                    "Prepare Monday action items.",
                    urgency="normal",
                )
                sent.append("sunday_review")

            # 3. API key rotation (check every 90 days)
            last_rotation = conn.execute(
                "SELECT detail FROM activity_log "
                "WHERE event_type = 'api_key_rotation' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if not last_rotation:
                # Never rotated — remind after system has been running 90 days
                oldest_trade = conn.execute(
                    "SELECT MIN(created_at) as first FROM shadow_trades"
                ).fetchone()
                if oldest_trade and oldest_trade["first"]:
                    from datetime import datetime as dt
                    try:
                        first = dt.fromisoformat(oldest_trade["first"].replace("Z", "+00:00"))
                        if (now - first.replace(tzinfo=ET if first.tzinfo is None else first.tzinfo)).days >= 90:
                            notify_action_required(
                                "Rotate API keys (90-day reminder)",
                                "Rotate: Alpaca, Anthropic, Finnhub, Polygon (if active).\n"
                                "Update config/settings.local.yaml and Render env vars.\n"
                                "Log: <code>python -m src.main log-activity api_key_rotation 'Rotated all keys'</code>",
                                urgency="normal",
                            )
                            sent.append("api_rotation")
                    except Exception as e:
                        logger.warning("[TELEGRAM] api_rotation date check failed: %s", e)

            # 4. Unscored training examples
            unscored = conn.execute(
                "SELECT COUNT(*) as c FROM training_examples "
                "WHERE quality_score_auto IS NULL OR quality_score_auto = 0"
            ).fetchone()
            unscored_count = unscored["c"] if unscored else 0
            if unscored_count > 100:
                notify_action_required(
                    f"Score training data ({unscored_count} unscored)",
                    f"{unscored_count} training examples need quality scoring.\n"
                    f"Run: <code>python -m src.main score-training-data</code>\n"
                    f"Cost: ~${unscored_count * 0.008:.2f} (Claude API)",
                    urgency="low",
                )
                sent.append("score_training")

            # 5. Saturday retrain check (Sundays — did Saturday retrain happen?)
            if now.weekday() == 6 and now.hour >= 10:
                active = conn.execute(
                    "SELECT version_name, created_at FROM model_versions "
                    "WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
                if active:
                    try:
                        from datetime import datetime as dt
                        created = dt.fromisoformat(active["created_at"].replace("Z", "+00:00"))
                        days_since = (now - created.replace(tzinfo=ET if created.tzinfo is None else created.tzinfo)).days
                        if days_since > 14:
                            notify_action_required(
                                f"Model retrain overdue ({days_since} days)",
                                f"Last retrain: {active['created_at'][:10]} ({active['version_name']})\n"
                                f"Run: <code>python -m src.main train --force</code>\n"
                                f"Or check Saturday overnight schedule logs.",
                                urgency="high",
                            )
                            sent.append("retrain_overdue")
                    except Exception as e:
                        logger.warning("[TELEGRAM] retrain_overdue date check failed: %s", e)

    except Exception as e:
        logger.debug("[TELEGRAM] Action reminder check failed: %s", e)

    return sent


def handle_command(command: str, args: str) -> str:
    """Process a Telegram command and return the response text.

    Available commands:
    /status — System status summary
    /trades — Open trades list
    /pnl — Current P&L
    /scan — Last scan results
    /earnings — Upcoming earnings
    /schedule — Compute schedule status
    /scoring — Scoring backlog
    /council — Run AI council session
    /help — List commands
    """
    try:
        if command == "/help" or command == "/start":
            return (
                "🤖 <b>ARCIS COMMANDS</b>\n\n"
                "/status — System status\n"
                "/trades — Open trades\n"
                "/pnl — Current P&L\n"
                "/scan — Last scan result\n"
                "/earnings — Upcoming earnings\n"
                "/schedule — Compute schedule\n"
                "/scoring — Scoring backlog\n"
                "/council — Run AI council session\n"
                "/health — GPU & system health\n"
                "/log — Recent activity log\n"
                "/pull — Git pull latest code\n"
                "/logs — Last 20 lines of arcis.log\n"
                "/gpu — GPU details (nvidia-smi)\n"
                "/disk — Disk usage\n"
                "/uptime — Watch loop uptime\n"
                "/heartbeat — Watchdog heartbeat age\n"
                "/help — This message"
            )

        elif command == "/status":
            return _cmd_status()
        elif command == "/trades":
            return _cmd_trades()
        elif command == "/pnl":
            return _cmd_pnl()
        elif command == "/scan":
            return _cmd_last_scan()
        elif command == "/earnings":
            return _cmd_earnings()
        elif command == "/schedule":
            return _cmd_schedule()
        elif command == "/scoring":
            return _cmd_scoring()
        elif command == "/council":
            return _cmd_council(args)
        elif command == "/health":
            return _cmd_health()
        elif command == "/log":
            return _cmd_log()
        elif command == "/pull":
            return _cmd_pull()
        elif command == "/logs":
            return _cmd_logs()
        elif command == "/gpu":
            return _cmd_gpu()
        elif command == "/disk":
            return _cmd_disk()
        elif command == "/uptime":
            return _cmd_uptime()
        elif command == "/heartbeat":
            return _cmd_heartbeat()
        else:
            return f"Unknown command: {command}\nSend /help for available commands."

    except Exception as e:
        return f"❌ Error: {str(e)[:200]}"


def _cmd_status() -> str:
    """System status summary."""
    now = datetime.now(ET)

    # Check Ollama directly instead of importing is_llm_available
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        llm_ok = resp.status_code == 200
    except Exception as e:
        logger.warning("[TELEGRAM] _cmd_status Ollama check failed: %s", e)
        llm_ok = False

    try:
        from src.training.versioning import get_active_model_name, get_training_example_counts
        model = get_active_model_name()
        counts = get_training_example_counts()
        total = counts['total']
    except Exception as e:
        logger.warning("[TELEGRAM] _cmd_status model info failed: %s", e)
        model = "unknown"
        total = "?"

    market_open = 9 <= now.hour < 16 and now.weekday() < 5

    return (
        f"🔧 <b>SYSTEM STATUS</b> ({now.strftime('%H:%M ET')})\n"
        f"LLM: {'✅' if llm_ok else '❌'} {model}\n"
        f"Training examples: {total}\n"
        f"Market: {'Open' if market_open else 'Closed'}"
    )


def _cmd_trades() -> str:
    """List open trades with paper/live split."""
    import sqlite3
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT ticker, entry_price, pnl_pct, pnl_dollars, created_at,
                       COALESCE(source, 'paper') as source
                FROM shadow_trades WHERE status = 'open' AND COALESCE(quarantined, 0) = 0
                ORDER BY source DESC, created_at DESC"""
            ).fetchall()

        if not rows:
            return "📭 No open trades."

        paper_trades = [r for r in rows if r["source"] == "paper"]
        live_trades = [r for r in rows if r["source"] == "live"]

        lines = [f"📊 <b>OPEN TRADES</b> ({len(rows)})"]

        if live_trades:
            lines.append(f"\n💰 <b>LIVE</b> ({len(live_trades)}):")
            for r in live_trades:
                pnl = float(r["pnl_pct"] or 0)
                emoji = "🟢" if pnl >= 0 else "🔴"
                try:
                    from datetime import datetime
                    opened = datetime.fromisoformat(r["created_at"][:19])
                    days = (datetime.now() - opened).days
                except Exception as e:
                    logger.warning("[TELEGRAM] _cmd_trades live days_held calc failed: %s", e)
                    days = "?"
                lines.append(
                    f"  {emoji} {r['ticker']}: ${float(r['entry_price'] or 0):.2f} "
                    f"({pnl:+.1f}%) Day {days}"
                )

        if paper_trades:
            lines.append(f"\n📝 <b>PAPER</b> ({len(paper_trades)}):")
            for r in paper_trades:
                pnl = float(r["pnl_pct"] or 0)
                emoji = "🟢" if pnl >= 0 else "🔴"
                try:
                    from datetime import datetime
                    opened = datetime.fromisoformat(r["created_at"][:19])
                    days = (datetime.now() - opened).days
                except Exception as e:
                    logger.warning("[TELEGRAM] _cmd_trades paper days_held calc failed: %s", e)
                    days = "?"
                lines.append(
                    f"  {emoji} {r['ticker']}: ${float(r['entry_price'] or 0):.2f} "
                    f"({pnl:+.1f}%) Day {days}"
                )

        return "\n".join(lines)
    except Exception as e:
        return f"📭 No open trades or error: {e}"


def _cmd_pnl() -> str:
    """Current P&L summary with paper/live split."""
    import sqlite3
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row

            # Overall stats
            open_row = conn.execute(
                """SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars), 0) as total_pnl
                FROM shadow_trades WHERE status = 'open' AND COALESCE(quarantined, 0) = 0"""
            ).fetchone()

            closed_row = conn.execute(
                """SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars), 0) as total_pnl,
                   COALESCE(AVG(CASE WHEN pnl_dollars > 0 THEN 1.0 ELSE 0.0 END), 0) as win_rate
                FROM shadow_trades WHERE status = 'closed' AND COALESCE(quarantined, 0) = 0"""
            ).fetchone()

            # Live-specific stats
            live_open = conn.execute(
                """SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars), 0) as total_pnl
                FROM shadow_trades WHERE status = 'open' AND source = 'live'
                AND COALESCE(quarantined, 0) = 0"""
            ).fetchone()

            live_closed = conn.execute(
                """SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars), 0) as total_pnl,
                   COALESCE(AVG(CASE WHEN pnl_dollars > 0 THEN 1.0 ELSE 0.0 END), 0) as win_rate
                FROM shadow_trades WHERE status = 'closed' AND source = 'live'
                AND COALESCE(quarantined, 0) = 0"""
            ).fetchone()

        open_pnl = open_row["total_pnl"]
        closed_pnl = closed_row["total_pnl"]
        total = open_pnl + closed_pnl
        emoji = "🟢" if total >= 0 else "🔴"

        lines = [
            f"{emoji} <b>P&L SUMMARY</b>",
            f"Open: {open_row['cnt']} trades, ${open_pnl:+.2f}",
            f"Closed: {closed_row['cnt']} trades, ${closed_pnl:+.2f}",
            f"Win rate: {closed_row['win_rate']:.0%}",
            f"Total: ${total:+.2f}",
        ]

        # Show live breakdown if any live trades exist
        live_total_cnt = live_open["cnt"] + live_closed["cnt"]
        if live_total_cnt > 0:
            live_pnl = live_open["total_pnl"] + live_closed["total_pnl"]
            live_emoji = "🟢" if live_pnl >= 0 else "🔴"
            lines.append(f"\n💰 <b>LIVE</b>: {live_emoji} ${live_pnl:+.2f}")
            lines.append(f"  Open: {live_open['cnt']} | Closed: {live_closed['cnt']}")
            if live_closed["cnt"] > 0:
                lines.append(f"  Win rate: {live_closed['win_rate']:.0%}")

            # Paper = total minus live
            paper_pnl = total - live_pnl
            paper_emoji = "🟢" if paper_pnl >= 0 else "🔴"
            paper_open = open_row["cnt"] - live_open["cnt"]
            paper_closed = closed_row["cnt"] - live_closed["cnt"]
            lines.append(f"\n📝 <b>PAPER</b>: {paper_emoji} ${paper_pnl:+.2f}")
            lines.append(f"  Open: {paper_open} | Closed: {paper_closed}")

        return "\n".join(lines)
    except Exception as e:
        logger.warning("[TELEGRAM] _cmd_pnl failed: %s", e)
        return "No P&L data available yet."


def _cmd_last_scan() -> str:
    """Last scan result."""
    import sqlite3
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT ticker, priority_score, created_at
                FROM recommendations ORDER BY created_at DESC LIMIT 5"""
            ).fetchall()

        if not rows:
            return "📭 No scans yet."

        lines = ["📊 <b>RECENT RECOMMENDATIONS</b>"]
        for r in rows:
            score = float(r["priority_score"] or 0)
            lines.append(f"  • {r['ticker']} (score: {score:.0f}) — {r['created_at'][:16]}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning("[TELEGRAM] _cmd_last_scan failed: %s", e)
        return "📭 No scan data available yet."


def _cmd_earnings() -> str:
    """Upcoming earnings."""
    try:
        from scripts.fetch_earnings_calendar import get_all_upcoming_earnings
        upcoming = get_all_upcoming_earnings(days=14)
        if not upcoming:
            return "📅 No earnings in the next 14 days."

        lines = [f"📅 <b>EARNINGS (next 14 days)</b> — {len(upcoming)} stocks"]
        for item in upcoming[:15]:
            lines.append(
                f"  • {item['ticker']} — {item['earnings_date']} "
                f"({item['days_away']}d) {item.get('earnings_time') or ''}"
            )
        if len(upcoming) > 15:
            lines.append(f"  ...and {len(upcoming) - 15} more")
        return "\n".join(lines)
    except Exception as e:
        return f"📅 Earnings data unavailable: {e}"


def _cmd_schedule() -> str:
    """Compute schedule status."""
    now = datetime.now(ET)
    hour = now.hour

    if 9 <= hour < 16 and now.weekday() < 5:
        phase = "🟢 MARKET HOURS — Scanning + between-scan scoring"
    elif 5 <= hour < 9:
        phase = "🌅 PRE-MARKET — Features, training gen, news scoring"
    elif 16 <= hour < 19:
        phase = "📝 POST-MARKET — Scoring, DPO generation"
    elif 19 <= hour or hour < 5:
        phase = "🌙 OVERNIGHT — Training pipeline active"
    else:
        phase = "⏸️ TRANSITION"

    return (
        f"⏰ <b>COMPUTE SCHEDULE</b> ({now.strftime('%H:%M ET')})\n"
        f"Phase: {phase}\n"
        f"Day: {'Weekday' if now.weekday() < 5 else 'Weekend'}\n"
        f"Target utilization: 73%"
    )


def _cmd_scoring() -> str:
    """Scoring backlog status."""
    import sqlite3
    try:
        with sqlite3.connect(DB_PATH) as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM training_examples"
            ).fetchone()[0]
            scored = conn.execute(
                "SELECT COUNT(*) FROM training_examples WHERE quality_score IS NOT NULL"
            ).fetchone()[0]
            unscored = total - scored

        return (
            f"📝 <b>SCORING STATUS</b>\n"
            f"Total examples: {total}\n"
            f"Scored: {scored}\n"
            f"Backlog: {unscored}"
        )
    except Exception as e:
        logger.warning("[TELEGRAM] _cmd_scoring failed: %s", e)
        return "📝 No scoring data available."


def _cmd_council(question: str = "") -> str:
    """Run an AI council session and format the result.

    If a question is provided (e.g., /council Should we buy the 3090?),
    runs a strategic session. Otherwise runs a daily tactical session.
    """
    try:
        from src.council.engine import run_council_command
        result = run_council_command(question)
    except Exception as e:
        return f"❌ Council session failed: {str(e)[:200]}"

    now = datetime.now(ET).strftime("%H:%M ET")
    direction = result.get("consensus", "unknown").upper()
    consensus_type = result.get("consensus_type", "?")
    confidence = result.get("confidence_avg", 0)

    lines = [f"🏛️ <b>AI COUNCIL SESSION</b> ({now})"]
    if question.strip():
        lines.append(f"📋 <i>{question.strip()[:100]}</i>")
    lines.append(f"Direction: <b>{direction}</b> ({consensus_type}, {confidence:.0%} avg confidence)")

    if result.get("is_contested"):
        lines.append("⚠️ <i>No consensus — required Round 2</i>")

    lines.append("")

    # V2 agent emoji and label mappings
    agent_emojis = {
        "tactical_operator": "⚡",
        "strategic_architect": "🏗️",
        "red_team": "🔴",
        "innovation_engine": "💡",
        "macro_navigator": "🌍",
    }
    agent_labels = {
        "tactical_operator": "Tactical",
        "strategic_architect": "Strategic",
        "red_team": "Red Team",
        "innovation_engine": "Innovation",
        "macro_navigator": "Macro",
    }

    # Use agent_assessments from v2 result
    assessments = result.get("agent_assessments", [])
    for assessment in assessments:
        agent = assessment.get("agent", "unknown")
        emoji = agent_emojis.get(agent, "⚪")
        label = agent_labels.get(agent, agent.replace("_", " ").title())
        direction_a = assessment.get("direction", "neutral")
        conf_a = assessment.get("confidence", 0)
        reasoning = assessment.get("key_reasoning", "")[:80]
        dir_emoji = {"bullish": "🟢", "neutral": "⚪", "bearish": "🔴"}.get(direction_a, "⚪")
        lines.append(f"{emoji} {label}: {dir_emoji} {direction_a} ({conf_a:.0%})")
        if reasoning:
            lines.append(f"   <i>{reasoning}...</i>")

    # Parameter adjustments
    params = result.get("parameter_adjustments", {})
    if params:
        lines.append("")
        for p, detail in params.items():
            if isinstance(detail, dict):
                prev = detail.get("previous", "?")
                applied = detail.get("applied", "?")
                if prev != applied:
                    lines.append(f"📊 {p}: {prev} → {applied}")

    if result.get("total_cost"):
        lines.append(f"\n💰 ${result['total_cost']:.4f} | Rounds: {result.get('rounds_completed', 0)}")

    return "\n".join(lines)


def _cmd_health() -> str:
    """GPU and system health."""
    import subprocess
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10
        )
        parts = result.stdout.strip().split(", ")
        temp, util, mem_used, mem_total = parts[0], parts[1], parts[2], parts[3]
        return (
            f"🖥️ <b>SYSTEM HEALTH</b>\n"
            f"GPU Temp: {temp}°C\n"
            f"GPU Util: {util}%\n"
            f"VRAM: {mem_used}/{mem_total} MB"
        )
    except Exception as e:
        logger.warning("[TELEGRAM] _cmd_health nvidia-smi failed: %s", e)
        return "🖥️ GPU health data unavailable (nvidia-smi not found)"


def _cmd_log() -> str:
    """Recent activity log entries."""
    try:
        from src.logging.activity import get_recent_activity

        entries = get_recent_activity(limit=10)
        if not entries:
            return "📋 No activity log entries yet."

        lines = ["📋 <b>RECENT ACTIVITY</b>"]
        for e in entries:
            # Extract time from ISO timestamp
            ts = e.get("timestamp", "")
            try:
                time_str = ts[11:16]  # HH:MM from ISO format
            except Exception as e:
                logger.warning("[TELEGRAM] _cmd_log timestamp parse failed: %s", e)
                time_str = "??:??"
            cat = e.get("category", "?")
            event = e.get("event", "")
            lines.append(f"{time_str} [{cat}] {event}")
        return "\n".join(lines)
    except Exception as e:
        return f"📋 Activity log unavailable: {e}"


def _cmd_pull() -> str:
    """Git pull latest code."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "pull"], capture_output=True, text=True, timeout=30
        )
        output = result.stdout.strip() or result.stderr.strip()
        return f"📥 <b>GIT PULL</b>\n<pre>{output[:500]}</pre>"
    except Exception as e:
        return f"❌ Git pull failed: {e}"


def _cmd_logs() -> str:
    """Last 20 lines of arcis.log."""
    import os
    log_path = os.path.join("logs", "arcis.log")
    try:
        with open(log_path, "r") as f:
            lines = f.readlines()
        last_20 = lines[-20:] if len(lines) >= 20 else lines
        text = "".join(last_20).strip()
        return f"📜 <b>LAST 20 LOG LINES</b>\n<pre>{text[:3500]}</pre>"
    except FileNotFoundError:
        return "📜 Log file not found"
    except Exception as e:
        return f"📜 Log read failed: {e}"


def _cmd_gpu() -> str:
    """GPU details via nvidia-smi."""
    import subprocess
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10
        )
        return f"🖥️ <b>GPU</b>\n<pre>{result.stdout.strip()[:1000]}</pre>"
    except Exception as e:
        logger.warning("[TELEGRAM] _cmd_gpu nvidia-smi failed: %s", e)
        return "🖥️ nvidia-smi not available"


def _cmd_disk() -> str:
    """Disk usage for key directories."""
    import os
    import shutil

    dirs = {
        "DB": DB_PATH,
        "Logs": "logs",
        "Models": "models",
    }
    lines = ["💾 <b>DISK USAGE</b>"]

    total, used, free = shutil.disk_usage(".")
    lines.append(f"Disk: {used // (1024**3)}GB / {total // (1024**3)}GB ({free // (1024**3)}GB free)")

    for label, path in dirs.items():
        if os.path.isfile(path):
            size = os.path.getsize(path) / (1024 * 1024)
            lines.append(f"  {label}: {size:.1f} MB")
        elif os.path.isdir(path):
            total_size = sum(
                os.path.getsize(os.path.join(dp, f))
                for dp, _, fns in os.walk(path) for f in fns
            ) / (1024 * 1024)
            lines.append(f"  {label}: {total_size:.1f} MB")
        else:
            lines.append(f"  {label}: not found")

    return "\n".join(lines)


def _cmd_uptime() -> str:
    """Watch loop uptime and next event."""
    now = datetime.now(ET)
    hour = now.hour

    # Determine next scheduled event
    if hour < 8:
        next_event = "Pre-market features at 8:00 ET"
    elif hour < 9:
        next_event = "Market open scan at 9:30 ET"
    elif 9 <= hour < 16:
        next_event = "Next scan in ~30 min"
    elif hour < 17:
        next_event = "Post-close capture at 17:30 ET"
    elif hour < 18:
        next_event = "Training collection at 18:00 ET"
    elif hour < 19:
        next_event = "Overnight training at 19:00 ET"
    else:
        next_event = "Data collection pipeline"

    return (
        f"⏱️ <b>UPTIME</b>\n"
        f"Time: {now.strftime('%Y-%m-%d %H:%M ET')}\n"
        f"Day: {now.strftime('%A')}\n"
        f"Next: {next_event}"
    )


def _cmd_heartbeat() -> str:
    """Report watchdog heartbeat age."""
    from pathlib import Path

    watchdog_file = Path("data/watchdog.txt")
    if not watchdog_file.exists():
        return "💔 <b>HEARTBEAT</b>\nNo watchdog file found — watch loop may not be running."

    try:
        last_beat = datetime.fromisoformat(watchdog_file.read_text().strip())
        now = datetime.now(ET)
        age_seconds = (now - last_beat).total_seconds()
        age_min = age_seconds / 60

        if age_min < 2:
            status = "💚 Healthy"
        elif age_min < 10:
            status = "💛 Delayed"
        else:
            status = "🔴 STALE — loop may be stuck"

        return (
            f"💓 <b>HEARTBEAT</b>\n"
            f"Last beat: {last_beat.strftime('%H:%M:%S ET')}\n"
            f"Age: {age_min:.1f} min\n"
            f"Status: {status}"
        )
    except Exception as e:
        return f"💔 <b>HEARTBEAT</b>\nError reading watchdog: {e}"
