# Training Data — Manual Backfill

## Workflow
1. Run: `python scripts/export_backfill_prompts.py`
2. Generate: copy prompts into Claude/ChatGPT, save responses to `results/`
3. Import: `python scripts/import_backfill_results.py --model claude_opus`
4. Check: `python scripts/backfill_progress.py`

## Folder Structure
- `prompts/` — exported feature snapshots organized by regime (DO NOT EDIT)
- `results/` — your saved responses (one file per prompt)
- `outcomes/` — sealed outcome data (DO NOT READ before generating)
- `progress.json` — auto-updated regime balance tracker

## Self-Blinding
The prompts contain ZERO outcome data. Outcomes are paired automatically
during import. Do not read outcomes.json before generating all responses.
