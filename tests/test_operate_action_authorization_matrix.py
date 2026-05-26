"""Tests for .claude/plugins/arcis/skills/operate/references/action-authorization-matrix.md

TDD acceptance tests per #109 T8 TEST_STRATEGY.
"""
import re
from pathlib import Path

MATRIX_PATH = Path(__file__).resolve().parents[1] / (
    ".claude/plugins/arcis/skills/operate/references/action-authorization-matrix.md"
)

VALID_VERIFICATION_VALUES = {"verified", "unverified-presumed", "removed"}
VALID_AUTH_CLASS_VALUES = {
    "auto-approved",
    "confirm",
    "confirm+safety_window",
    "emergency-only-in-window",
}

EXPECTED_HEADER_COLUMNS = [
    "Action",
    "Verification",
    "Auth class",
    "CLI invocation",
    "Verify step",
    "Risk",
    "Notes",
]


def _get_table_rows(content: str):
    """Return all pipe-delimited rows from the first markdown table found."""
    lines = content.splitlines()
    in_table = False
    rows = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            in_table = True
            rows.append(stripped)
        elif in_table:
            # End of table block
            break
    return rows


def _parse_cells(row: str):
    """Split a markdown table row into cells, stripping whitespace."""
    # Remove leading/trailing pipes, then split
    inner = row.strip("|")
    cells = [c.strip() for c in inner.split("|")]
    return cells


def test_file_exists():
    assert MATRIX_PATH.exists(), f"Missing file: {MATRIX_PATH}"


def test_has_7_column_table():
    content = MATRIX_PATH.read_text(encoding="utf-8")
    rows = _get_table_rows(content)
    assert rows, "No markdown table found in the file"
    header_row = rows[0]
    cells = _parse_cells(header_row)
    assert cells == EXPECTED_HEADER_COLUMNS, (
        f"Header columns mismatch.\n  Expected: {EXPECTED_HEADER_COLUMNS}\n  Got:      {cells}"
    )


def test_all_rows_have_7_cells():
    content = MATRIX_PATH.read_text(encoding="utf-8")
    rows = _get_table_rows(content)
    assert rows, "No markdown table found"
    # Skip header (row 0) and separator (row 1)
    data_rows = [r for r in rows[2:] if r.strip()]
    assert data_rows, "No data rows found in table"
    for row in data_rows:
        cells = _parse_cells(row)
        assert len(cells) == 7, (
            f"Row has {len(cells)} cells (expected 7): {row}"
        )


def test_verification_values_in_enum():
    content = MATRIX_PATH.read_text(encoding="utf-8")
    rows = _get_table_rows(content)
    assert rows, "No markdown table found"
    data_rows = [r for r in rows[2:] if r.strip()]
    assert data_rows, "No data rows found"
    for row in data_rows:
        cells = _parse_cells(row)
        verification = cells[1]
        assert verification in VALID_VERIFICATION_VALUES, (
            f"Verification value '{verification}' not in {VALID_VERIFICATION_VALUES}"
        )
    # Post-impl gate: no row should be left as 'unverified-presumed'
    verifications = [_parse_cells(r)[1] for r in data_rows]
    assert "unverified-presumed" not in verifications, (
        "After impl-time probe, no row should remain 'unverified-presumed'"
    )


def test_auth_class_values_in_enum():
    content = MATRIX_PATH.read_text(encoding="utf-8")
    rows = _get_table_rows(content)
    assert rows, "No markdown table found"
    data_rows = [r for r in rows[2:] if r.strip()]
    assert data_rows, "No data rows found"
    for row in data_rows:
        cells = _parse_cells(row)
        auth_class = cells[2]
        assert auth_class in VALID_AUTH_CLASS_VALUES, (
            f"Auth class '{auth_class}' not in {VALID_AUTH_CLASS_VALUES}"
        )


def test_utf8_clean():
    raw = MATRIX_PATH.read_bytes()
    decoded = raw.decode("utf-8")
    assert len(decoded) > 0
