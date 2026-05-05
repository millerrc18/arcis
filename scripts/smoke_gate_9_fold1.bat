@echo off
REM Gate #9 — first-fold smoke for §B2 admissibility (real LLM calls)
python scripts/generate_llm_corpus.py --corpus-id stage1-fold1 --folds 1 --window-start 2023-09-01 --window-end 2026-04-28
