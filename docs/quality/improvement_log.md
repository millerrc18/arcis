# Improvement Log

## 2026-04-05 — Reduced false-positive markdown rejection in ingestion gate
- **Improvement:** Updated `src/training/ingestion_gate.py` so markdown-bold rejection targets line-leading bold markdown formatting patterns, while allowing inline emphasis.
- **Why it matters:** Keeps the anti-markdown quality gate intact but avoids unnecessary training halts from benign inline formatting.
- **Evidence:** `pytest tests/test_ingestion_gate.py` and new inline-bold regression test.

## 2026-04-05 — Hardened markdown-bold structural detection coverage
- **Improvement:** Expanded markdown-bold detection to cover list-prefixed line-leading bold headings and end-of-line heading forms, while preserving acceptance of inline bold emphasis in prose.
- **Why it matters:** Improves ingestion determinism by blocking additional structural markdown contamination patterns without reintroducing prior false positives.
- **Evidence:** `PYTHONPATH=. pytest -q tests/test_ingestion_gate.py` with new tests for rejected bold headings and accepted inline punctuation emphasis.

## 2026-04-05 — Improved Telegram halt reason clarity for faster triage
- **Improvement:** Added reason hints in `alert_training_halt` so Telegram alerts now include contextual detail for markdown-related reasons (for example, `markdown_bold (line-leading **bold** markdown heading)`).
- **Why it matters:** Reduces operator ambiguity during incidents and shortens root-cause investigation time when batch compliance halts occur.
- **Evidence:** `PYTHONPATH=. pytest -q tests/test_ingestion_gate.py` with `test_alert_training_halt_includes_reason_hint`.

## 2026-04-06 — Hardened overnight watch reliability from log-derived failures
- **Improvement:** Implemented type-safe coercion in research notifications and pre-market digest/brief confidence handling, and corrected fundamentals refresh to use active macro/earnings collectors.
- **Why it matters:** Prevents repeated overnight scheduler errors (`Unknown format code`, `<= not supported`, missing import targets) and restores expected scheduled data refresh/notification behavior.
- **Evidence:** `PYTHONPATH=. pytest -q tests/test_expanded_notifications.py tests/test_digest_builder.py tests/test_fundamentals_refresh.py`.
