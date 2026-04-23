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

## 2026-04-06 — Added GitHub issue coverage for every active branch problem
- **Improvement:** Opened and linked issue tickets for all branch workstreams (fixed + pending): #299, #300, #301, #302, #303, #304.
- **Why it matters:** Establishes durable tracking, accountability, and clear handoff for unresolved operational items discovered in overnight logs.
- **Evidence:** GitHub issue URLs:
  - https://github.com/millerrc18/halcyon-lab/issues/299
  - https://github.com/millerrc18/halcyon-lab/issues/300
  - https://github.com/millerrc18/halcyon-lab/issues/301
  - https://github.com/millerrc18/halcyon-lab/issues/302
  - https://github.com/millerrc18/halcyon-lab/issues/303
  - https://github.com/millerrc18/halcyon-lab/issues/304

## 2026-04-22 — Added explicit triage playbook for training collection drop-offs
- **Improvement:** Added a dedicated investigation report with ranked root-cause candidates, code-path analysis, and production SQL diagnostics to pinpoint where candidates are being filtered.
- **Why it matters:** Converts a vague "no examples collected" symptom into a deterministic step-by-step debug workflow and prevents repeated ad hoc investigations.
- **Evidence:** `docs/quality/training_collection_investigation_2026-04-22.md`; `pytest -q tests/test_self_blinding.py tests/test_data_collectors.py -k "training_examples_from_closed_trades or TrainingDataCollectorPnlTypeSafety"`; `pytest -q tests/shadow_trading/test_reconcile_partial_fill_mismatch.py`.

## 2026-04-22 — Training collector now handles closed trades without recommendation linkage
- **Improvement:** Relaxed training collector eligibility to include closed, non-quarantined trades even when `recommendations` linkage is absent, with deterministic fallback dedupe keys for null `recommendation_id` records.
- **Why it matters:** Restores training flywheel continuity for reconciled/legacy rows that still represent real closed outcomes but were previously invisible to collection.
- **Evidence:** `pytest -q tests/test_data_collectors.py -k "without_recommendation_row_still_collects or without_recommendation_id_uses_trade_fallback_key"`; `pytest -q tests/test_self_blinding.py tests/test_data_collectors.py -k "training_examples_from_closed_trades or TrainingDataCollectorPnlTypeSafety or without_recommendation"`.
