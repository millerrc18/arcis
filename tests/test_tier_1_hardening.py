"""Regression guards for Tier 1 hardening (#619, #578, #437, #482, #436).

Each test prevents the corresponding bug pattern from re-emerging via
source-scan assertions (similar to tests/test_dep_health_hardening.py).
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# #619 — RotatingFileHandler must specify encoding="utf-8"
# ---------------------------------------------------------------------------


def test_log_config_file_handler_uses_utf8_encoding(tmp_path):
    """#619 — RotatingFileHandler must specify encoding='utf-8' so emoji
    and CJK characters are written to the log file instead of being
    silently dropped via the cp1252 fallback on Windows.

    Behavioral test: configure logging to a tmp file, emit an emoji
    record, then read the file as utf-8 and assert the emoji round-trips.
    On Windows without encoding='utf-8', this raises UnicodeEncodeError
    inside logging.handleError() and the record is dropped.
    """
    import logging

    from src.log_config import setup_logging

    log_file = tmp_path / "test.log"
    setup_logging(level="INFO", log_file=str(log_file))

    logger = logging.getLogger("tier1.utf8.test")
    # ❌ is ❌ (cross mark) — fails to encode under cp1252
    logger.error("emoji marker ❌ here")

    # Force flush all root handlers so the file is written before we read.
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:
            pass

    text = log_file.read_text(encoding="utf-8")
    assert "❌" in text, (
        "Emoji was dropped — RotatingFileHandler likely missing encoding='utf-8' "
        "(cp1252 fallback on Windows silently discards records with non-encodable chars)"
    )


def test_log_config_source_declares_utf8_on_file_handler():
    """Source-scan guard: the literal RotatingFileHandler(...) call in
    src/log_config.py must include encoding="utf-8" so future edits don't
    silently regress the behavioral fix above."""
    src = _read("src/log_config.py")
    # Match RotatingFileHandler( ... ) across newlines
    match = re.search(r"RotatingFileHandler\s*\((.*?)\)", src, re.DOTALL)
    assert match, "RotatingFileHandler call not found in src/log_config.py"
    args = match.group(1)
    assert 'encoding="utf-8"' in args or "encoding='utf-8'" in args, (
        "RotatingFileHandler must explicitly pass encoding='utf-8' (#619)"
    )
