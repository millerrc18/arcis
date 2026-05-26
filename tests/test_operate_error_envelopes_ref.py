"""Tests for .claude/plugins/arcis/skills/operate/references/error-envelopes.md

TDD: verify the file exists with all 9 sections and required structure.
"""
import re
from pathlib import Path

REF_PATH = Path(__file__).resolve().parents[1] / (
    ".claude/plugins/arcis/skills/operate/references/error-envelopes.md"
)


def test_file_exists():
    assert REF_PATH.exists(), f"Missing reference file: {REF_PATH}"


def test_nine_sections_present():
    content = REF_PATH.read_text(encoding="utf-8")
    h2_sections = re.findall(r"^## ", content, re.MULTILINE)
    assert len(h2_sections) >= 9, (
        f"Expected >=9 ## sections, found {len(h2_sections)}"
    )


def test_audit_write_failure_section_present():
    content = REF_PATH.read_text(encoding="utf-8")
    # §10.9 must be present — DA3-mandated
    found = bool(
        re.search(r"(?i)(audit.{0,20}writ.{0,20}fail|10\.9)", content)
    )
    assert found, "§10.9 audit write failure section not found"


def test_each_section_has_trigger_output_audit_exit():
    content = REF_PATH.read_text(encoding="utf-8")
    # Split into per-section chunks by ## heading
    chunks = re.split(r"^## ", content, flags=re.MULTILINE)
    # Skip preamble (first chunk before any ##)
    sections = chunks[1:]
    assert len(sections) >= 9
    for section in sections:
        title_line = section.splitlines()[0]
        assert re.search(r"\*\*Trigger", section), (
            f"Section '{title_line}' missing **Trigger"
        )
        assert re.search(r"\*\*Output", section), (
            f"Section '{title_line}' missing **Output"
        )
        assert re.search(r"\*\*Audit", section), (
            f"Section '{title_line}' missing **Audit"
        )
        assert re.search(r"\*\*Exit", section), (
            f"Section '{title_line}' missing **Exit"
        )


def test_utf8_clean():
    raw = REF_PATH.read_bytes()
    # Must decode as valid UTF-8 without errors
    decoded = raw.decode("utf-8")
    assert len(decoded) > 0
