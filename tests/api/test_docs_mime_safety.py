"""Regression tests for Sprint 0 cluster-07 Critical #4 — DOCS MIME safety.

The /docs/{doc_id} route used to call ``fp.read_text(encoding="utf-8")``
unconditionally on any DOCS-whitelisted path. Several DOCS entries are
binary (.pdf, .docx) — calling ``read_text`` on them raises
``UnicodeDecodeError`` which propagated as HTTP 500 with a Python traceback
that leaks file path info.

The fix:
1. Reject non-text suffixes with HTTP 415 BEFORE attempting read_text.
2. Wrap read_text in try/except UnicodeDecodeError as a defensive backstop.

Tests must FAIL on the pre-fix code (raw 500/UnicodeDecodeError leak) and
PASS on the fix (HTTP 415 with clean message).

Called by: pytest (CI)
Calls: src.api.routes.docs
Owns tables: none
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from src.api.routes import docs as docs_module
from src.api.routes.docs import TEXT_DOC_SUFFIXES, get_doc


# ── TEXT_DOC_SUFFIXES whitelist sanity check ─────────────────────────────────


class TestTextSuffixWhitelist:
    """Lock the whitelist down so future edits can't quietly add a binary type."""

    def test_includes_markdown(self):
        assert ".md" in TEXT_DOC_SUFFIXES

    def test_includes_plain_text(self):
        assert ".txt" in TEXT_DOC_SUFFIXES

    def test_excludes_pdf(self):
        assert ".pdf" not in TEXT_DOC_SUFFIXES

    def test_excludes_docx(self):
        assert ".docx" not in TEXT_DOC_SUFFIXES

    def test_is_immutable_frozenset(self):
        """frozenset prevents accidental .add() at runtime."""
        assert isinstance(TEXT_DOC_SUFFIXES, frozenset)


# ── Route behavior tests ─────────────────────────────────────────────────────


class TestDocsRouteRejectsBinaryExtensions:
    """The route must return HTTP 415 for binary suffixes BEFORE read_text fires."""

    def test_docs_route_rejects_binary_extension_with_415(self, tmp_path):
        """A .pdf entry in DOCS must produce HTTP 415, not 500/UnicodeDecodeError.

        Patches DOCS to include a fake .pdf entry and verifies the suffix
        check rejects it before read_text is attempted. This is the canonical
        regression for Sprint 0 cluster-07 Critical #4.
        """
        # Create a real on-disk binary file so fp.exists() is True
        # (which means we get past the 404 guard and hit the suffix check).
        fake_pdf = tmp_path / "fake.pdf"
        # PDF magic bytes — real binary content. read_text would raise
        # UnicodeDecodeError on these.
        fake_pdf.write_bytes(b"%PDF-1.4\n\x00\x01\xff\xfe binary content")

        fake_docs = [
            {"id": "test-pdf", "path": "fake.pdf", "title": "Test PDF"},
        ]
        with patch.object(docs_module, "DOCS", fake_docs), \
             patch.object(docs_module, "_find_project_root", return_value=tmp_path):
            with pytest.raises(HTTPException) as exc_info:
                get_doc("test-pdf")

        assert exc_info.value.status_code == 415
        assert ".pdf" in str(exc_info.value.detail) or "Unsupported" in str(exc_info.value.detail)

    def test_docs_route_rejects_docx_extension_with_415(self, tmp_path):
        """A .docx entry must also produce HTTP 415 (sibling check)."""
        fake_docx = tmp_path / "fake.docx"
        # DOCX is a ZIP — magic bytes
        fake_docx.write_bytes(b"PK\x03\x04 binary docx content")

        fake_docs = [
            {"id": "test-docx", "path": "fake.docx", "title": "Test DOCX"},
        ]
        with patch.object(docs_module, "DOCS", fake_docs), \
             patch.object(docs_module, "_find_project_root", return_value=tmp_path):
            with pytest.raises(HTTPException) as exc_info:
                get_doc("test-docx")

        assert exc_info.value.status_code == 415

    def test_docs_route_rejects_no_extension_with_415(self, tmp_path):
        """Unknown / missing suffix is treated as non-text and rejected."""
        fake_file = tmp_path / "noextension"
        fake_file.write_bytes(b"\x00\x01\xff binary blob")

        fake_docs = [
            {"id": "test-no-ext", "path": "noextension", "title": "No Ext"},
        ]
        with patch.object(docs_module, "DOCS", fake_docs), \
             patch.object(docs_module, "_find_project_root", return_value=tmp_path):
            with pytest.raises(HTTPException) as exc_info:
                get_doc("test-no-ext")

        assert exc_info.value.status_code == 415

    def test_docs_route_handles_unicode_decode_error_gracefully(self, tmp_path):
        """Defensive backstop: if a future text suffix is added that holds
        binary content, never leak the raw UnicodeDecodeError traceback.

        Forces the path through by registering a fake .md file containing
        invalid UTF-8 bytes. Suffix check passes (.md is whitelisted), so
        read_text is attempted; the UnicodeDecodeError must be caught and
        converted to HTTP 415, not propagated as 500.
        """
        # .md suffix passes the whitelist check, but content is invalid UTF-8.
        # Bytes 0x80, 0x81 are continuation bytes that can't start a UTF-8
        # codepoint, so utf-8 decode fails.
        fake_md = tmp_path / "binary.md"
        fake_md.write_bytes(b"\x80\x81\x82 not valid utf-8")

        fake_docs = [
            {"id": "test-bad-utf8", "path": "binary.md", "title": "Bad UTF-8"},
        ]
        with patch.object(docs_module, "DOCS", fake_docs), \
             patch.object(docs_module, "_find_project_root", return_value=tmp_path):
            with pytest.raises(HTTPException) as exc_info:
                get_doc("test-bad-utf8")

        # Must surface as 415 (clean message), NOT raw UnicodeDecodeError → 500.
        assert exc_info.value.status_code == 415
        # Detail must NOT include the underlying decode-error traceback details.
        detail = str(exc_info.value.detail)
        assert "UnicodeDecodeError" not in detail
        assert "Traceback" not in detail


class TestDocsRouteAllowsTextExtensions:
    """The fix must NOT break legitimate .md / .txt / .json reads."""

    def test_md_extension_returns_content(self, tmp_path):
        fake_md = tmp_path / "real.md"
        fake_md.write_text("# Hello\n\nMarkdown body.", encoding="utf-8")

        fake_docs = [
            {"id": "test-md", "path": "real.md", "title": "Real MD"},
        ]
        with patch.object(docs_module, "DOCS", fake_docs), \
             patch.object(docs_module, "_find_project_root", return_value=tmp_path):
            result = get_doc("test-md")

        assert result["id"] == "test-md"
        assert result["title"] == "Real MD"
        assert "Hello" in result["content"]

    def test_txt_extension_returns_content(self, tmp_path):
        fake_txt = tmp_path / "notes.txt"
        fake_txt.write_text("plain text", encoding="utf-8")

        fake_docs = [
            {"id": "test-txt", "path": "notes.txt", "title": "Notes"},
        ]
        with patch.object(docs_module, "DOCS", fake_docs), \
             patch.object(docs_module, "_find_project_root", return_value=tmp_path):
            result = get_doc("test-txt")

        assert result["content"] == "plain text"


class TestDocsRouteCurrentWhitelistSafety:
    """All currently-whitelisted DOCS entries must have either a text suffix
    or already be flagged as binary in the route. This test catches a future
    edit that adds a new binary type without updating the whitelist."""

    def test_all_docs_entries_have_known_suffix(self):
        """Every DOCS entry's suffix is either in TEXT_DOC_SUFFIXES (will
        be served as text) or in {.pdf, .docx} (known download-only binary
        types). Any other suffix would be a silent bug — the route would
        415 it and the dashboard couldn't render it OR download it."""
        from pathlib import Path
        known_binary = {".pdf", ".docx"}
        for doc in docs_module.DOCS:
            suffix = Path(doc["path"]).suffix.lower()
            assert (
                suffix in TEXT_DOC_SUFFIXES or suffix in known_binary
            ), (
                f"DOCS entry {doc['id']!r} (path={doc['path']!r}) has suffix "
                f"{suffix!r} that is neither text-readable nor a known binary "
                f"type. Either add the suffix to TEXT_DOC_SUFFIXES or remove "
                f"the entry."
            )
