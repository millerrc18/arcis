@echo off
REM Gate #9 (capped) — fold-1 plumbing smoke with 100-decision cap.
REM
REM Verifies the full LLM call path end-to-end (corpus_id, fetch, slice,
REM enrichment, prompt build, LLM call, parse, write) without committing to
REM the multi-day cost of the full fold. Different corpus-id than the real
REM fold-1 run so the corpus directory isn't polluted.
REM
REM Expected runtime: ~30-60 minutes (100 entries x ~30 sec/entry).
python scripts/generate_llm_corpus.py --corpus-id stage1-capped --folds 1 --window-start 2023-09-01 --window-end 2026-04-28 --max-decisions 100
