# Sprint Documentation Checklist

> Streamlined April 1, 2026. Old version required 12+ file updates per sprint — unsustainable.
> Counts now live in SYSTEM_STATE.md only. Drift is caught by `scripts/verify_docs.py`.

## After Every Sprint

### Required (always)

- [ ] **SYSTEM_STATE.md** — Update header, sprint table, counts section. This is the sole source of truth for all metrics.
- [ ] **CHANGELOG.md** — Add sprint entry with date and feature list.

### If Applicable

- [ ] **AGENTS.md** — Only if governance, scope, architecture overview, or data sources changed. NOT for counts (those go in SYSTEM_STATE.md).
- [ ] **config/settings.example.yaml** — If new config keys were added to code.
- [ ] **scripts/render_migrate.py** — If new Postgres tables or columns were added.

### Automated Verification

Run at the end of every sprint:

```bash
python scripts/verify_docs.py    # Compares actual counts to SYSTEM_STATE.md
python -m pytest tests/ -x -q    # Tests must pass
cd frontend && npm run build     # Frontend must build
```

## What NOT to Update Manually

These items are now handled automatically or removed from the mandatory list:

| Old Requirement | Why Removed |
|-----------------|-------------|
| AGENTS.md counts (8 metrics) | Counts live in SYSTEM_STATE.md only. AGENTS.md is governance, not metrics. |
| architecture.md module registry | Stale within hours. Will be auto-generated when refreshed. |
| README.md counts | Points to SYSTEM_STATE.md for current numbers. |
| docs/system-state snapshots | SYSTEM_STATE.md is the living snapshot. Git history is the archive. |

## Anti-Patterns

- Never duplicate counts in multiple files — update SYSTEM_STATE.md only
- Never add a config key without adding it to `settings.example.yaml`
- Never add a DB table without adding it to `render_migrate.py`
- Run `verify_docs.py` before declaring a sprint complete
