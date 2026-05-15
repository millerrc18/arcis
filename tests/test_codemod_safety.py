"""Tests for `src/utils/codemod.py` — codemod runner with rollback-on-parse-failure.

Context: 2026-05-15 v0.36.8 shipped a 41-site `except sqlite3.X:` migration
via an ad-hoc Python script. The script's import-extension logic had a
regex bug for multi-line parenthesized imports, corrupting
`src/scheduler/watch.py:49` into a SyntaxError. The watch loop service
was Paused for ~10 minutes until v0.36.9 patched it.

Root cause: the v0.36.8 codemod ran without a post-migration parse check.
The lint test passed (regex-based, doesn't invoke the Python parser) and
shipped the syntax error. The codemod-runner module enforces:

  1. Snapshot every targeted file before applying the transform.
  2. After applying, run `py_compile` on every modified `.py` file.
  3. If ANY file fails to parse, revert ALL changes to their snapshots.
  4. Raise `CodemodError` with the per-file parse errors.

Future codemods (cross-engine migrations, refactors, library upgrades)
go through `apply_codemod` so the v0.36.8 failure class can't recur.
"""
from __future__ import annotations

from pathlib import Path

import pytest


class TestApplyCodemodHappyPath:
    def test_simple_transform_writes_changes(self, tmp_path):
        from src.utils.codemod import apply_codemod

        f = tmp_path / "module.py"
        f.write_text("x = 1\ny = 2\n")

        def transform(path, text):
            return text.replace("x = 1", "x = 10")

        result = apply_codemod([f], transform)

        assert result["modified"] == [f]
        assert result["skipped"] == []
        assert f.read_text() == "x = 10\ny = 2\n"

    def test_multiple_files_all_succeed(self, tmp_path):
        from src.utils.codemod import apply_codemod

        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        f1.write_text("a = 1\n")
        f2.write_text("b = 2\n")

        def transform(path, text):
            return text.replace("=", " = ")  # no-op-ish: normalize whitespace

        result = apply_codemod([f1, f2], transform)
        # Both files were "modified" (text changed, even if to equivalent value)
        assert len(result["modified"]) == 2


class TestApplyCodemodRollback:
    def test_syntax_error_in_one_file_rolls_back_all(self, tmp_path):
        """The v0.36.8 bug class: one file gets a SyntaxError, all others revert."""
        from src.utils.codemod import apply_codemod, CodemodError

        good = tmp_path / "good.py"
        bad = tmp_path / "bad.py"
        good.write_text("x = 1\n")
        bad.write_text("y = 2\n")

        def transform(path, text):
            if path.name == "bad.py":
                # Inject a SyntaxError — mimics the v0.36.8 import-extension bug
                return "from foo import (, BadImport\n    bar,\n)\n"
            return text.replace("x = 1", "x = 10")

        with pytest.raises(CodemodError) as exc_info:
            apply_codemod([good, bad], transform)

        # ALL files reverted to original content
        assert good.read_text() == "x = 1\n", "good.py should have been rolled back"
        assert bad.read_text() == "y = 2\n", "bad.py should have been rolled back"
        # Error message names the offending file
        assert "bad.py" in str(exc_info.value)

    def test_v0_36_8_exact_bug_class_is_caught(self, tmp_path):
        """Replays the EXACT v0.36.8 import-mangle and asserts rollback.

        Closing the regression-lock loop: a codemod that produces
            from src.utils.db import (, DBError
                _scalar,
                ...
            )
        must be detected and reverted.
        """
        from src.utils.codemod import apply_codemod, CodemodError

        original_import = (
            "from src.utils.db import (\n"
            "    _scalar,\n"
            "    connect_db,\n"
            ")\n"
            "logger = logging.getLogger(__name__)\n"
        )
        f = tmp_path / "watch.py"
        f.write_text(original_import)

        def buggy_codemod(path, text):
            # The exact regex bug from v0.36.8: insert the new import after
            # `(` rather than as a new line inside the parens.
            return text.replace(
                "from src.utils.db import (\n",
                "from src.utils.db import (, DBError\n",
            )

        with pytest.raises(CodemodError):
            apply_codemod([f], buggy_codemod)
        # File reverted
        assert f.read_text() == original_import


class TestApplyCodemodNoOpAndDryRun:
    def test_identical_transform_skips_file(self, tmp_path):
        from src.utils.codemod import apply_codemod

        f = tmp_path / "noop.py"
        f.write_text("x = 1\n")
        mtime_before = f.stat().st_mtime_ns

        def identity(path, text):
            return text

        result = apply_codemod([f], identity)
        assert result["modified"] == []
        assert result["skipped"] == [f]
        # File content unchanged; mtime should not have advanced
        # (file was never written).
        assert f.stat().st_mtime_ns == mtime_before

    def test_dry_run_reports_but_does_not_write(self, tmp_path):
        from src.utils.codemod import apply_codemod

        f = tmp_path / "dry.py"
        original = "x = 1\n"
        f.write_text(original)

        def transform(path, text):
            return text.replace("x = 1", "x = 99")

        result = apply_codemod([f], transform, dry_run=True)
        assert result["modified"] == [f]
        # On-disk content unchanged
        assert f.read_text() == original


class TestApplyCodemodEdgeCases:
    def test_py_compile_skipped_for_non_py_files(self, tmp_path):
        """Non-.py files (e.g., .json, .md) should never trigger py_compile."""
        from src.utils.codemod import apply_codemod

        f = tmp_path / "config.json"
        f.write_text('{"old": "value"}\n')

        def transform(path, text):
            return text.replace("old", "new")

        result = apply_codemod([f], transform)
        assert result["modified"] == [f]
        assert "new" in f.read_text()

    def test_py_compile_check_can_be_disabled(self, tmp_path):
        """`py_compile_check=False` allows syntax errors through.

        Useful for non-Python codemods or intentional intermediate states.
        Caller takes responsibility.
        """
        from src.utils.codemod import apply_codemod

        f = tmp_path / "bad.py"
        f.write_text("x = 1\n")

        def transform(path, text):
            return "this is not python\n"

        # No exception — check disabled
        result = apply_codemod([f], transform, py_compile_check=False)
        assert result["modified"] == [f]
        assert f.read_text() == "this is not python\n"
