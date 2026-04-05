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
