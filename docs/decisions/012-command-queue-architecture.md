# ADR 012: Pull-Based Command Queue for Dashboard Control Plane

**Status:** Active
**Date:** 2026-03-30
**Sprint:** 4C

## Context

The cloud dashboard (halcyonlab.app) was read-only. All action endpoints returned "must be done locally." Settings could not be edited remotely. The only remote control was Telegram `/halt`.

We need the dashboard to be a full control plane: trigger scans, run council sessions, adjust settings, halt/resume trading, and view logs.

## Decision

Use a **pull-based command queue** pattern with Render Postgres as the intermediary.

```
Dashboard writes → Render Postgres (pending_commands)
    ↓ pull on sync cycle
Local watch loop executes command
    ↓ push on next sync
Render Postgres (command_results) → Dashboard reads result
```

## Why Pull-Based (Not Push)

1. **No inbound connections:** Render cannot push to the local machine. There is no public endpoint on the local machine and no NAT traversal.
2. **Existing infrastructure:** The local machine already syncs to Render Postgres every 120s via `render_sync.py`. We ride this existing thread.
3. **Simplicity:** No WebSocket server, no webhook endpoints, no port forwarding, no Cloudflare tunnel.
4. **Resilience:** If the local machine is offline, commands queue up and execute when it reconnects. No lost messages.

## Latency

- Command submission: instant (dashboard writes to Postgres)
- Execution: 0-120 seconds (next sync cycle pulls commands)
- For emergencies: Telegram `/halt` remains the fastest path (~1s)

## Safety Rules

1. Commands expire after 5 minutes (stale commands are discarded)
2. Config changes only affect whitelisted keys (no API keys, DB paths, or secrets)
3. All results truncated to 10KB (prevent large payloads)
4. Rate limit: max 10 commands per minute
5. `close-position` requires a valid ticker in payload

## Schema

4 new tables:
- `pending_commands` — written by dashboard, pulled by local
- `command_results` — written by local, read by dashboard
- `config_overrides` — written by dashboard, pulled by local (full table replace)
- `log_entries` — written by local, read by dashboard (last 500 entries)

## Alternatives Considered

| Approach | Rejected Because |
|----------|-----------------|
| WebSocket push from Render | No inbound connections to local machine |
| Cloudflare Tunnel | Extra infrastructure dependency, security surface |
| Telegram bot for all commands | Poor UX for settings, no structured data |
| SSH reverse tunnel | Fragile, requires port management |

## Consequences

- Dashboard actions now work in cloud mode (0-120s latency)
- Settings can be changed from halcyonlab.app without local access
- Log viewer provides remote observability
- Telegram `/halt` remains the fastest emergency path
- 4 new DB tables to maintain
