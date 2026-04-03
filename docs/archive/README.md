# docs/archive/

Archived documentation moved here during Sprint A (April 2026) when MASTER.md was created as the single consolidated governance document.

## What was moved and why

### governance/ (absorbed into MASTER.md)

| File | Original Location | Absorbed Into |
|---|---|---|
| SYSTEM_STATE.md | repo root | MASTER.md Sections 2, 5, 6, 7, 8, 11 |
| AGENTS.md | repo root | MASTER.md Sections 1, 3, 4, 9, 12 |
| conventions.md | docs/ | MASTER.md Section 9 |
| sprint-checklist.md | docs/ | MASTER.md Section 9 |
| schema-governance.md | docs/ | MASTER.md Section 4 |

### reference/ (superseded by source of truth)

| File | Why Archived |
|---|---|
| architecture.md | Stale module registry; interactive diagram at halcyonlab.app/architecture replaces it |
| database-schema.md | Schema registry (`src/schema/registry.py`) is the single source of truth |
| dependency-graph.md | Stale within hours of any code change |
| roadmap.md | Dashboard Roadmap page is the live version |
| roadmap-complete.md | Superseded by dashboard Roadmap page |
| diagrams.md | Replaced by React Flow interactive diagrams |

## Policy

- **Do not delete archived files** — git history matters for traceability
- **Do not update archived files** — they represent a point-in-time snapshot
- **All new governance updates** go into MASTER.md
