# Wave 3 Receipt

**Operator fills in this template after completing Wave 3.**  
Date completed: `__________`  
Operator: `__________`

---

## 1. Smoke test results

Copy results from `wave-3-smoke-test-checklist.md`. Mark each row Pass/Fail and add notes.

| # | Page | URL | Result | Notes |
|---|------|-----|--------|-------|
| 1 | Dashboard | `https://halcyonlab.app` | `[ ] Pass  [ ] Fail` | |
| 2 | Trade History | `https://halcyonlab.app/trades` | `[ ] Pass  [ ] Fail` | |
| 3 | Council | `https://halcyonlab.app/council` | `[ ] Pass  [ ] Fail` | |
| 4 | Notifications Health | `https://halcyonlab.app/notifications` | `[ ] Pass  [ ] Fail` | |
| 5 | Platform / Walk-forward | `https://halcyonlab.app/platform` | `[ ] Pass  [ ] Fail` | |
| 6 | WebSocket `/ws/live` | DevTools WS tab | `[ ] Pass  [ ] Fail` | |

Smoke test overall: `[ ] ALL PASS — proceeded to decommission`  
`[ ] ONE OR MORE FAILED — decommission deferred (describe below)`

Failure details (if any):
```
(paste here)
```

---

## 2. Render decommission completion

| Service | Deleted | Timestamp (UTC) |
|---------|---------|-----------------|
| `halcyon-api` (Render API service) | `[ ] Yes  [ ] No` | `__________` |
| `halcyon-frontend` (Render frontend service) | `[ ] Yes  [ ] No` | `__________` |
| Render Postgres instance | `[ ] Retained (cold backup until 2026-05-17)` | leave alive |

Post-deletion curl result for Render API (`curl https://halcyon-api.onrender.com/healthz`):
```
(paste output — expected: 404 or NXDOMAIN)
```

Post-deletion curl result for tunnel (`curl ... https://halcyonlab.app/healthz`):
```
(paste output — expected: {"status":"ok"} HTTP 200)
```

---

## 3. DNS cleanup decisions

Cloudflare zone audit for `onrender.com` CNAMEs — records found:

| Record name | Target | Action taken |
|-------------|--------|--------------|
| `(paste)` | `(paste)` | `[ ] Deleted  [ ] Kept — reason: __________` |
| `(paste)` | `(paste)` | `[ ] Deleted  [ ] Kept — reason: __________` |

If no `onrender.com` CNAMEs were found, write: `No onrender.com CNAME records found in zone.`

---

## 4. Final acceptance statement

Wave 3 is complete when the operator can sign all four lines below:

- `[ ]` All 6 smoke test pages passed via `https://halcyonlab.app`
- `[ ]` `halcyon-api` and `halcyon-frontend` Render services deleted
- `[ ]` Render Postgres retained; calendar reminder set for 2026-05-17
- `[ ]` DNS cleanup complete; no stale `onrender.com` CNAMEs active

**Operator sign-off:**

```
Name: __________
Date: __________
Notes: __________
```

Once all four checkboxes are marked, Wave 3 is officially closed. Proceed to Wave 4
(engine-aware `connect_db` shim and data migration planning).
