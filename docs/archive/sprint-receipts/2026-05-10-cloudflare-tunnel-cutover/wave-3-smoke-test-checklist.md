# Wave 3 Smoke Test Checklist

**Goal:** Confirm all six dashboard pages load with real data through the Cloudflare Tunnel
(`halcyonlab.app`), with no CORS errors and WebSocket connectivity verified, before the
operator proceeds to Render decommission. All six must pass before filling in `wave-3-receipt.md`.

---

## Per-page checklist

| # | Page | URL | Expected behavior | Pass | Notes |
|---|------|-----|-------------------|------|-------|
| 1 | Dashboard | `https://halcyonlab.app` | SPA loads; KPI strip shows real numbers (not zero/null placeholders); no 401/403 in network tab | `[ ]` | Try `?cb=<timestamp>` to bust cache if stale build |
| 2 | Trade History | `https://halcyonlab.app/trades` | Trade history table renders; pagination controls respond; at least 1 row visible | `[ ]` | If no rows, confirm watch loop has run at least one scan since NSSM restart |
| 3 | Council | `https://halcyonlab.app/council` | Council recommendations load; no "failed to fetch" toast; data is non-empty | `[ ]` | Empty council is OK if no signals today; no error state is the gate |
| 4 | Notifications Health | `https://halcyonlab.app/notifications` | Notifications health widget visible; status indicator shows OK or degraded (not error/spinner-loop) | `[ ]` | Degraded is acceptable if Render sync thread is in graceful-fail state |
| 5 | Platform / Walk-forward | `https://halcyonlab.app/platform` | Platform page renders; walk-forward results table or chart present; no blank page | `[ ]` | If walk-forward is empty, confirm data pipeline has run post-cutover |
| 6 | WebSocket `/ws/live` | `https://halcyonlab.app/ws/live` (verify in DevTools) | In Chrome DevTools → Network → WS tab: connection shows status 101; messages flowing (or idle but connected) | `[ ]` | Open DevTools **before** navigating to dashboard; filter `ws://` or `wss://`; look for the `/ws/live` handshake row |

---

## How to run

1. Open Chrome with DevTools open (F12 → Network tab → filter `WS`).
2. Navigate to each URL in the table above.
3. Check each expected behavior. Mark `[x]` for pass, `[FAIL: <note>]` for any failure.
4. For page 6 (WebSocket), the connection upgrade shows as a row in the WS filter with HTTP 101; click it to see frames.

## Additional checks (all 6 pages)

- No CORS errors in the Console tab (red `Access-Control-Allow-Origin` messages).
- No 401/403 responses in the Network tab — if present, the `Authorization` header from the frontend is not being sent; check `VITE_API_SECRET` in `frontend/.env.production` and rebuild.
- `watchdog.txt` is updating (`type C:\arcis\data\watchdog.txt` in a terminal) — confirms the NSSM-managed watch loop is alive.

---

## Acceptance

**All 6 pages pass → operator pastes results into `wave-3-receipt.md`.**

If any page fails, resolve the issue before proceeding to Render decommission
(see `wave-3-render-decommission-runbook.md` §1).
