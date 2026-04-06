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
