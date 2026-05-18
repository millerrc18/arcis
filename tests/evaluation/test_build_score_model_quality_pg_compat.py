"""W21 P2-3 regression-lock: `_score_model_quality()` must access named columns.

Pre-fix SQL:
  SELECT SUM(llm_success), SUM(llm_total) FROM scan_metrics WHERE ...

PG (psycopg2 RealDictCursor) collapses both un-aliased SUMs to the same
column name `sum`, so the resulting dict has 1 entry. Indexing `row[1]`
then IndexErrors with "list index out of range" — visible in logs as
`[BuildScore] model_quality error: list index out of range` firing daily
at ~16:45 ET.

Fix:
- Alias the SUMs: `SUM(llm_success) AS success_sum, SUM(llm_total) AS total_sum`
- Access by name: `row['success_sum']`, `row['total_sum']`

This is a file-content regression-lock — full behavioral testing requires
a scan_metrics fixture across both engines.
"""

import os


_BUILD_SCORE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "src", "evaluation", "build_score.py",
)


def _load_source() -> str:
    with open(_BUILD_SCORE_PATH, encoding="utf-8") as f:
        return f.read()


def test_score_model_quality_uses_aliased_sums():
    """The SUM columns must be aliased in the SQL."""
    source = _load_source()
    idx = source.find("def _score_model_quality")
    assert idx > 0, "_score_model_quality function not found"
    end = source.find("\ndef ", idx + 5)
    block = source[idx:end if end > 0 else idx + 1500]

    assert "AS success_sum" in block, (
        "_score_model_quality must alias SUM(llm_success) AS success_sum "
        "for PG compat (RealDictCursor collapses un-aliased SUMs)"
    )
    assert "AS total_sum" in block, (
        "_score_model_quality must alias SUM(llm_total) AS total_sum"
    )


def test_score_model_quality_accesses_by_name_not_int_index():
    """Named access required to avoid 'list index out of range' on PG."""
    source = _load_source()
    idx = source.find("def _score_model_quality")
    end = source.find("\ndef ", idx + 5)
    block = source[idx:end if end > 0 else idx + 1500]

    assert 'success_sum' in block and 'total_sum' in block, (
        "_score_model_quality must reference success_sum / total_sum"
    )
    # The exact pre-fix bug pattern must not remain.
    assert "if row and row[1] and row[1] > 0:" not in block, (
        "Pre-fix `if row and row[1]` pattern must be replaced with "
        "named-column access guard"
    )
