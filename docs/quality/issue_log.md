# Issue Log

## 2026-04-05 — Training halted from strict markdown bold detection
- **Issue:** The ingestion gate rejected any `**...**` pair anywhere in commentary and surfaced `markdown_bold` as the top halt reason.
- **Impact:** Batches could halt even when XML structure was valid and the only markdown contamination was inline emphasis in prose.
- **Fix:** Scoped `markdown_bold` detection to line-leading bold markdown labels/headings instead of all inline emphasis.
- **Evidence:** `pytest tests/test_ingestion_gate.py`.

## 2026-04-05 — `markdown_bold` detector missed key structural variants
- **Issue:** The narrowed pattern could still miss line-leading markdown-bold variants (for example numbered/bulleted lines or bold headings ending at line end without trailing spaces).
- **Impact:** Some structurally contaminated markdown lines could slip through ingestion and reduce format discipline over time.
- **Fix:** Hardened the regex to detect list-prefixed bold headings and end-of-line heading forms, and added explicit tests for both rejection and safe inline punctuation emphasis.
- **Evidence:** `PYTHONPATH=. pytest -q tests/test_ingestion_gate.py`.

## 2026-04-05 — Telegram halt reason lacked actionable context
- **Issue:** Halt alerts displayed only raw reason codes, which made markdown-related investigations slower (`markdown_bold` gave no immediate clue about the concrete rejected pattern).
- **Impact:** Operators had to inspect code to interpret reasons during an active ingestion halt.
- **Fix:** Added reason hints to alert payloads and covered the message contract with a unit test.
- **Evidence:** `PYTHONPATH=. pytest -q tests/test_ingestion_gate.py`.

## 2026-04-06 — Overnight watch run showed type/import runtime failures
- **Issue:** Logs show unresolved runtime faults in three paths: `notify_research_papers` formatting error when `top_score` is a string, pre-market brief confidence math failing on string DB values, and Tier-4 fundamentals refresh importing non-existent collector symbols/modules.
- **Impact:** Telegram paper notifications and pre-market brief/digest reliability were degraded, and scheduled fundamentals refresh skipped intended data updates.
- **Fix:** Added numeric coercion guards for research and digest/brief confidence formatting, and switched fundamentals refresh imports to current collectors (`collect_macro_snapshots`, `fetch_earnings_dates`) with test coverage.
- **Evidence:** `PYTHONPATH=. pytest -q tests/test_expanded_notifications.py tests/test_digest_builder.py tests/test_fundamentals_refresh.py`.

## 2026-04-06 — GitHub issues opened for all active branch workstreams
- **Issue:** Branch-level reliability and data-quality fixes lacked explicit upstream GitHub issue tracking.
- **Impact:** Harder to coordinate ownership, triage, and follow-on remediation across fixed and still-open defects.
- **Fix:** Opened six GitHub issues covering fixed workstreams and remaining unresolved items:
  - #299 ingestion markdown gate scope
  - #300 pre-market digest/brief type safety
  - #301 fundamentals refresh import drift
  - #302 render sync NULL-id hygiene
  - #303 research source resilience (403/404 feeds)
  - #304 VRAM handoff reload timeout reliability
- **Evidence:** GitHub API issue creation responses (201) with URLs `https://github.com/millerrc18/halcyon-lab/issues/299` through `/304`.

## 2026-04-22 — Training examples not appearing after trade completion
- **Issue:** Operators observed that completed trades were not producing new training examples.
- **Impact:** Training data flywheel appears stalled, reducing trust in post-trade learning cadence.
- **Fix:** Performed an exhaustive code-path investigation and documented all hard eligibility gates and failure modes in `docs/quality/training_collection_investigation_2026-04-22.md`.
- **Evidence:** `pytest -q tests/test_self_blinding.py tests/test_data_collectors.py -k "training_examples_from_closed_trades or TrainingDataCollectorPnlTypeSafety"`; `pytest -q tests/shadow_trading/test_reconcile_partial_fill_mismatch.py`.

## 2026-04-22 — Closed trades dropped from training collection when recommendation linkage was missing
- **Issue:** The collector required an inner join to `recommendations` and deduped only by `recommendation_id`, so closed trades with missing recommendation rows or null recommendation IDs were excluded and never became pending training examples.
- **Impact:** Operators could observe newly closed trades without any corresponding increase in pending/collected training examples.
- **Fix:** Switched collector candidate query to `LEFT JOIN recommendations`, added dedupe by a stable fallback key (`trade:<trade_id>`) when `recommendation_id` is missing, and persisted that key in `training_examples.recommendation_id`.
- **Evidence:** `pytest -q tests/test_data_collectors.py -k "without_recommendation_row_still_collects or without_recommendation_id_uses_trade_fallback_key"`; `pytest -q tests/test_self_blinding.py tests/test_data_collectors.py -k "training_examples_from_closed_trades or TrainingDataCollectorPnlTypeSafety or without_recommendation"`.
