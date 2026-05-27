# SQLite Debris Archive — 2026-05-27

This directory holds a single artifact moved out of the repo root by Phase 5 PR-A
under the T1b safety-classification protocol (`docs/audits/2026-05-27-phase-5-unified/master-spec.md`).

## Why this exists

The repo root had an `ai_research_desk.sqlite3` file that was an active violation
of `CLAUDE.md:26` — the canonical runtime SQLite database lives at
`C:/arcis/data/ai_research_desk.sqlite3` per the `ARCIS_DB_PATH` configuration in
`.env`. A second SQLite file at the repo root creates a confusing parallel DB
that no production code reads from, but that adb-aware tooling could pick up by
mistake.

## T1b decision-matrix evidence

| Criterion | Repo-root file | Canonical | SCRATCH? |
|---|---|---|---|
| Size | 0 bytes | 566 MB (566,943,744) | YES (root < canon × 0.5) |
| mtime | 2026-04-26 | 2026-05-27 (31 days newer) | YES (>7 days older) |
| Table count | 0 tables | 82 tables | YES |

All 3 indicators flag SCRATCH → MOVE per the protocol decision matrix
(see master-spec PR-A T1b Step 5, branch ALL-SCRATCH).

The contents (0 bytes) carry no data — the move is purely structural so the
new `test_no_sqlite_at_repo_root` rule passes and so any future operator
inspecting the repo root sees no SQLite file there.

## Provenance

- Decided procedurally by PM (PR-A autonomous dispatch) on 2026-05-27.
- The `.sqlite3` file itself is gitignored (`.gitignore:34` — global `*.sqlite3`
  pattern). This README is the tracked audit-trail artifact; the SQLite file
  lives here as physical evidence but is invisible to `git status`.

## Retention

This archive directory may be deleted in Phase-6 once Phase 5 PR-A is well-
established and no operator-investigation references it. Until then, treat as
write-once read-rarely.
