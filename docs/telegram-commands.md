# Telegram Bot Command Reference

Halcyon Lab includes a Telegram bot for real-time notifications and interactive commands. The bot pushes alerts for trade opens/closes, earnings warnings, overnight data collection, system events, and more. It also accepts commands for quick status checks from your phone.

## Setup

Add the following to `config/settings.local.yaml`:

```yaml
telegram:
  enabled: true
  bot_token: "your-bot-token"
  chat_id: "your-chat-id"
```

Test delivery with: `python -m src.main send-test-telegram`

## Commands

### /status

System status summary including LLM availability, active model, training example count, and market hours.

**Example response:**
```
SYSTEM STATUS (14:32 ET)
LLM: OK halcyon-v1
Training examples: 976
Market: Open
```

### /trades

Lists all open trades split by paper and live accounts. Shows ticker, entry price, unrealized P&L percentage, and holding duration.

**Example response:**
```
OPEN TRADES (3)

LIVE (1):
  AAPL: $187.50 (+2.1%) Day 3

PAPER (2):
  MSFT: $412.30 (+1.4%) Day 5
  NVDA: $890.10 (-0.8%) Day 2
```

### /pnl

Current profit & loss summary across all accounts. Shows open/closed trade counts, cumulative P&L, and win rate, with a live/paper breakdown when live trades exist.

**Example response:**
```
P&L SUMMARY
Open: 3 trades, $+145.20
Closed: 12 trades, $+523.80
Win rate: 67%
Total: $+669.00

LIVE: $+87.50
  Open: 1 | Closed: 2
  Win rate: 100%

PAPER: $+581.50
  Open: 2 | Closed: 10
```

### /scan

Shows the most recent trade recommendations from the last scan cycle, including ticker, priority score, and timestamp.

**Example response:**
```
RECENT RECOMMENDATIONS
  - AAPL (score: 82) -- 2026-03-25 14:30
  - MSFT (score: 76) -- 2026-03-25 14:30
  - NVDA (score: 71) -- 2026-03-25 14:30
```

### /earnings

Upcoming earnings dates for S&P 100 stocks within the next 14 days. Useful for managing event risk on open positions.

**Example response:**
```
EARNINGS (next 14 days) -- 8 stocks
  - AAPL -- 2026-04-01 (6d) after_close
  - MSFT -- 2026-04-03 (8d) after_close
  - GOOGL -- 2026-04-05 (10d) after_close
  ...and 5 more
```

### /schedule

Shows the current compute schedule phase based on time of day. Phases include market hours (scanning), pre-market (features/news), post-market (scoring/DPO), and overnight (training).

**Example response:**
```
COMPUTE SCHEDULE (14:32 ET)
Phase: MARKET HOURS -- Scanning + between-scan scoring
Day: Weekday
Target utilization: 73%
```

### /scoring

Training data scoring backlog. Shows total examples, how many have been scored by the LLM-as-judge, and how many remain in the backlog.

**Example response:**
```
SCORING STATUS
Total examples: 976
Scored: 890
Backlog: 86
```

### /council

Triggers an on-demand AI Council session (Delphi protocol). Five specialized agents (Risk Officer, Alpha Strategist, Data Scientist, Regime Analyst, Devil's Advocate) deliberate across 3 rounds to reach consensus on current market positioning.

**Example response:**
```
AI COUNCIL SESSION (14:32 ET)
Consensus: CAUTIOUS_LONG (72% confidence)

Risk Officer: REDUCE_EXPOSURE (8/10)
Alpha Strategist: MAINTAIN_LONG (7/10)
Data Scientist: MAINTAIN_LONG (6/10)
Regime Analyst: CAUTIOUS_LONG (7/10)
Devil's Advocate: REDUCE_EXPOSURE (5/10)
```

### /health

GPU and system health check. Reports Ollama LLM status, GPU memory usage, disk space, and database size.

**Example response:**
```
SYSTEM HEALTH
Ollama: OK
GPU: 8.2 / 12.0 GB (68%)
Disk: 45.2 GB free
DB: 128 MB
```

### /log

Recent activity log showing the last 10 system events (scans, trades, training runs, data collection, etc.).

**Example response:**
```
RECENT ACTIVITY (last 10)
  14:30 scan_complete -- 3 packet-worthy, 8 watchlist
  14:00 scan_complete -- 1 packet-worthy, 12 watchlist
  13:30 trade_opened -- AAPL $187.50
  09:30 market_open -- Starting scan cycle
  ...
```

### /help

Lists all available commands with short descriptions. Also triggered by `/start` when first interacting with the bot.

## Notification Types

In addition to commands, the bot sends automatic push notifications for:

| Event | Description |
|-------|-------------|
| Trade opened | New paper or live position entered |
| Trade closed | Position exited with P&L |
| Earnings warning | Open position has earnings within 5 days |
| Scan complete | Summary of each scan cycle result |
| Data collection | Overnight pipeline start/completion |
| Training | Model training events (start, complete, rollback) |
| Risk alerts | Kill switch, daily loss limit, or other governor triggers |
| System errors | Critical failures requiring attention |
