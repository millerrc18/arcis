# Cutover-State Corpus Verification — Stage 1

**Date:** 2026-05-11
**Sprint:** S1-CC A4 (Stage 1 Corpus Closeout)
**Purpose:** Confirm the Stage 1 corpus (`data/corpus/stage1-001/`) is operationally independent of the Modified-A migration (PR #1047 wrapper cutover + PR #1048 Phase 0 + ongoing Phase 1/2).

## Filesystem audit

`data/corpus/stage1-001/` contents (verified 2026-05-11 against `C:\arcis\halcyon-lab\data\corpus\stage1-001\`):

- `entries.jsonl` — 202,924,097 bytes, 67,528 rows (matches `manifest.json:total_decision_points`)
- `manifest.json` — 901 bytes; admissibility PASS, walkforward window 2023-09-01 → 2026-04-28
- `entries.jsonl.bak.31984.pre_big_trim` — pre-trim historical artifact (86 MB, 2026-05-06)
- `entries.jsonl.bak.32021` — pre-trim historical artifact (87 MB, 2026-05-06)

**No SQLite files** in the corpus dir — verified by `find data/corpus/ -name "*.sqlite*" -o -name "*.db" -o -name "*.sql"` (zero results). No non-JSONL/manifest files exist.

## Registry audit

`src/schema/registry.py` grep for corpus/stage1/training table definitions (case-insensitive):

- **No** `corpus_runs` table.
- **No** `stage1_runs`, `stage1_*`, or `training_corpora` table.
- **No** `corpus_metadata` registry entry of any kind.
- The `training_examples` table (registry line 457) exists, but it is the curated instruction/output pair store for fine-tuning — sourced from real trades + synthetic generation + manual curation. It is NOT the Stage 1 JSONL corpus and is written by `data_collector`/`synthetic_generator`, not by the corpus generator at `src/evaluation/corpus_generator.py`.
- Companion training tables (`model_versions`, `preference_pairs`, `canary_evaluations`, `quality_drift_metrics`) are likewise distinct from the Stage 1 JSONL corpus — they track training-cycle outputs, not corpus-generation source data.

## Migration-survival assessment

The Stage 1 corpus exists as bare JSONL on the filesystem; it does NOT participate in the SQLite ↔ Postgres write path that the Modified-A migration converts. Specifically:

- The Modified-A migration touches `src/utils/db.py` (`connect_db` wrapper), 16 production call sites with `INSERT OR REPLACE/IGNORE` statements (Phase 1 / PR #1049), and 17 sites with `PRAGMA` / `sqlite_master` / `julianday` queries (Phase 2, in progress).
- The corpus files at `data/corpus/stage1-001/` are read by `src/evaluation/corpus.py:load_entries_by_decision` and `src/evaluation/backtester.py:88-91` via `Path()` + `open()` + `json.loads`, NOT via `connect_db()`. The corpus root is configurable via `ARCIS_CORPUS_ROOT` env var (corpus.py:225) and defaults to `data/corpus/`.
- The corpus generator at `src/evaluation/corpus_generator.py` streams `CorpusEntry` rows directly to `entries.jsonl` (line 163) — no SQLite involvement.
- No migration-touched code path opens, reads, or writes any file under `data/corpus/`.

**Conclusion: INDEPENDENT.** Sprint S1-CC's Batch A artifacts (`MANIFEST.sha256` from A1, `composition-audit.md` from A2, `cold-read.md` from A3) survive any future Modified-A cutover unchanged. The Stage 1 corpus closeout is operationally independent of all migration phases — pinning, audit, and cold-read findings reference filesystem state untouched by `src/utils/db.py` wrapper rewiring or downstream call-site migration.
