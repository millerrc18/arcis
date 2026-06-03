"""Helper package for the W21 capstone clean-slate wipe (#95).

Modules:
  classification  — WIPE/KEEP frozensets + EXPECTED_FK_EDGES + partition guard.
  live_schema     — live-prod schema + FK reconciliation (authoritative gate).
  backup          — pg_dump + verify + fresh-ephemeral-DB restore-compare.
  sqlite_retire   — archive-fsync-then-empty the legacy SQLite residue.
  config_verify   — read-only config/Ollama post-reset assertion.

The orchestration + decorated public entry point live in
scripts/clean_slate_wipe.py (which imports this package).
"""
