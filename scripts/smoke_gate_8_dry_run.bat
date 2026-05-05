@echo off
REM Gate #8 — dry-run smoke for §B2 admissibility (no LLM calls)
python scripts/generate_llm_corpus.py --corpus-id stage1-smoke --window-start 2024-01-01 --window-end 2024-01-31 --dry-run --max-decisions 100
