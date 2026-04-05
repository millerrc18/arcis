# Arcis Dashboard (Frontend)

React 19 + Tailwind 4 + Vite 8 dashboard for the Arcis trading system.

## Setup

```bash
cd frontend
npm install
npm run dev
```

The dev server starts on `http://localhost:5173` by default and proxies API requests to the local FastAPI backend on port 8000.

For cloud mode, set `VITE_API_URL` and `VITE_IS_CLOUD=true` before building:

```bash
VITE_API_URL=https://halcyon-api.onrender.com/api VITE_IS_CLOUD=true npm run build
```

## Pages

| Page | Route | Description |
|------|-------|-------------|
| Dashboard | `/` | Paper equity, open/closed trades, win rate, activity feed |
| Shadow Ledger | `/shadow` | Paper trading ledger with metrics |
| Live Ledger | `/live` | Live trading positions and summary |
| CTO Report | `/cto-report` | Performance analytics and audit |
| Training | `/training` | Training examples, model versions, quality report |
| Health | `/health` | HSHS score, Build Score, system health dimensions |
| Council | `/council` | AI Council session history and votes |
| Settings | `/settings` | API costs, config overrides |
| Validation | `/validation` | System validation checks |
| Logs | `/logs` | Recent log entries |
| DB Schema | `/schema` | Table row counts for all 49 tables |
| Packets | `/packets` | Trade recommendation packets |
| Docs | `/docs` | Research documents |
| Notes | `/notes` | User notes (CRUD) |
| Architecture | `/architecture` | Static architecture diagram |
| Roadmap | `/roadmap` | Static roadmap |
| Attribution | `/attribution` | Alpha attribution stats (ranker vs LLM) |
| Stress Test | `/stress-test` | Historical stress test scenario results |

## Stack

- **React 19** with functional components and hooks
- **Tailwind 4** via `@tailwindcss/vite` plugin
- **TanStack Query** for server state (30s refetch, 10s stale time)
- **React Router 7** for client-side routing
- **Recharts** for charts
- **Lucide React** for icons
- **WebSocket** context for real-time cache invalidation

## Cloud Mode

When `VITE_IS_CLOUD=true`, the app wraps all routes in an `AuthGate` component that prompts for the `API_SECRET` token. The token is stored in `localStorage` and sent as a `Bearer` header on every API request.
