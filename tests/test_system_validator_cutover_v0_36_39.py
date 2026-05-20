"""Regression-lock for v0.36.39 — system_validator: gut Render + fix PG-cutover false warnings.

Today's 16:30 EOD validation returned CRITICAL (41P / 15W / 1F). Investigation found
the noise was almost entirely validator bugs, not real system problems:

- **1 FAIL** = `api_render_connection` (Render Postgres). Render hosting is fully
  deprecated post one-DB cutover (2026-05-18) — a permanent false CRITICAL.
  Gutted (with `api_render_config` + the onrender.com `api_cloud_healthz`).
- **Cascade of false "not accessible" warnings** (model_versions / canary /
  last_retrain / quality_drift): the curriculum query used column `stage` but the
  real column is `curriculum_stage` → UndefinedColumn on PG → aborted transaction
  with no rollback → every subsequent query on that connection failed. Fixed the
  column + added a rollback in `_safe_query`.
- **`activity_log` / `council_sessions` "not accessible"**: `row[0][:19]` sliced a
  PG `datetime` (PG returns datetime objects for `MAX(created_at)`, not strings) →
  TypeError. Fixed by wrapping all timestamp slices in `str()`.
- **`research_docs` "table not found"**: the collector date-column map used
  `created_at` but the column is `updated_at`.

These are all PG-cutover impedance bugs. The remaining warnings (thin training
corpus, orphaned rec_ids, zombie trades) are GENUINE and intentionally untouched.
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

_SRC = Path("src/evaluation/system_validator.py").read_text(encoding="utf-8")


def test_no_render_or_cloud_checks_remain():
    """Render hosting is deprecated — its validator checks must be gone."""
    from src.evaluation.system_validator import _check_api
    with patch("requests.get", side_effect=Exception("no network in test")):
        checks = _check_api({"render": {"enabled": True, "database_url": "postgresql://x"}})
    names = [c["name"] for c in checks]
    assert not any("render" in n for n in names), f"render checks still present: {names}"
    assert "api_cloud_healthz" not in names, "deprecated onrender.com cloud healthz still present"
    # the legitimate local checks remain
    assert "api_local_server" in names


def test_safe_query_rolls_back_on_failure():
    """A failed query must roll back so it can't poison the PG transaction and
    cascade false 'not accessible' onto subsequent checks."""
    from src.evaluation.system_validator import _safe_query
    conn = MagicMock()
    conn.execute.side_effect = Exception("relation does not exist")
    result = _safe_query(conn, "SELECT 1 FROM missing_table")
    assert result is None
    conn.rollback.assert_called_once()


def test_curriculum_uses_correct_column():
    """The curriculum query must use curriculum_stage (the real column), not the
    non-existent `stage` that triggered the cascade."""
    assert "curriculum_stage" in _SRC
    assert not re.search(r"SELECT\s+stage\s*,", _SRC), "curriculum query still uses bare `stage`"


def test_no_bare_timestamp_slice_on_fetched_values():
    """All timestamp slices must be str()-wrapped — PG returns datetime objects,
    not strings, so a bare `row[0][:19]` raises TypeError on the cutover DB."""
    bad = re.findall(r"(?<!str\()\brow\[[01]\]\[:19\]", _SRC)
    assert not bad, f"un-wrapped timestamp slice(s) remain (will TypeError on PG): {bad}"
    bad_scan = re.findall(r"(?<!str\()\blast_scan\[:19\]", _SRC)
    assert not bad_scan, f"un-wrapped last_scan slice(s) remain: {bad_scan}"


def test_research_docs_uses_updated_at_column():
    """research_docs has no created_at column — the date-column map must use updated_at."""
    assert '"research_docs": "updated_at"' in _SRC
    assert '"research_docs": "created_at"' not in _SRC
