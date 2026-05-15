"""Codemod runner with snapshot/rollback safety + post-migration parse check.

Context: 2026-05-15 v0.36.8 shipped a 41-site mechanical migration via an
ad-hoc Python script. The script's regex-based import-extension had a
bug for multi-line parenthesized imports, corrupting
``src/scheduler/watch.py:49`` into a SyntaxError. The watch loop service
was Paused for ~10 min until v0.36.9 patched it.

Root cause: the migration ran without a post-migration parse check. The
lint test (`tests/test_no_naked_sqlite_exceptions.py`) is regex-based —
it scans file text, never invokes Python's parser. A syntax error in an
import statement that doesn't touch the lint's regex passes the lint and
ships.

This module enforces the safety pattern for every future codemod:

  1. **Snapshot** every targeted file before applying the transform.
  2. **Apply** the transform file-by-file, writing changes to disk.
  3. **Verify** every modified `.py` file via `py_compile`.
  4. **Rollback** ALL files to their snapshots if ANY file fails to parse,
     then raise `CodemodError` with per-file errors.

Usage::

    from src.utils.codemod import apply_codemod
    from pathlib import Path

    def transform(path: Path, original: str) -> str:
        # Return the new file content, or `original` to skip.
        return original.replace("old_pattern", "new_pattern")

    result = apply_codemod([Path("a.py"), Path("b.py")], transform)
    # result == {"modified": [...], "skipped": [...]}

Called by: any future bulk-migration script (cross-engine renames,
library upgrades, defensive sweeps).
Calls: pathlib, py_compile.
Owns tables: none.
Tests: tests/test_codemod_safety.py
"""
from __future__ import annotations

import py_compile
from pathlib import Path
from typing import Callable


class CodemodError(Exception):
    """Raised when a codemod's post-migration parse check fails.

    Before raising, every modified file is reverted to its pre-codemod
    snapshot. The caller can re-run after fixing the transform.
    """


def apply_codemod(
    file_paths: list[Path],
    transform: Callable[[Path, str], str],
    *,
    py_compile_check: bool = True,
    dry_run: bool = False,
) -> dict:
    """Apply ``transform`` to each file with snapshot/rollback safety.

    Args:
        file_paths: Files to migrate (any extension; only ``.py`` files are
            parse-checked when ``py_compile_check=True``).
        transform: ``f(path, original_content) -> new_content``. Return
            ``original_content`` (or an identical string) to skip the file.
        py_compile_check: If True (default), run ``py_compile`` on every
            modified ``.py`` file after writing. If any file fails to parse,
            revert ALL files (including non-Python files) to their snapshots
            and raise ``CodemodError``. Disable only for non-Python codemods
            or intentional intermediate states (caller assumes responsibility).
        dry_run: If True, report what would change but don't write to disk.
            Returns the same shape dict (with ``modified`` listing files that
            WOULD have been changed).

    Returns:
        ``{"modified": [Path, ...], "skipped": [Path, ...]}``.

    Raises:
        CodemodError: when ``py_compile_check`` is enabled and at least one
            modified ``.py`` file fails to parse. All files are rolled back
            to their original content before raising.
    """
    snapshots: dict[Path, str] = {}
    modified: list[Path] = []
    skipped: list[Path] = []

    for p in file_paths:
        p = Path(p)
        original = p.read_text(encoding="utf-8")
        snapshots[p] = original
        new_content = transform(p, original)
        if new_content == original:
            skipped.append(p)
            continue
        if dry_run:
            modified.append(p)
            continue
        p.write_text(new_content, encoding="utf-8")
        modified.append(p)

    if py_compile_check and not dry_run:
        errors: list[tuple[Path, str]] = []
        for p in modified:
            if p.suffix != ".py":
                continue
            try:
                py_compile.compile(str(p), doraise=True)
            except py_compile.PyCompileError as exc:
                errors.append((p, str(exc)))

        if errors:
            # Rollback every snapshot — including files that did parse —
            # so the working tree is exactly as it was before the codemod.
            for snap_path, original in snapshots.items():
                snap_path.write_text(original, encoding="utf-8")
            error_lines = "\n".join(f"  {p}: {msg}" for p, msg in errors)
            raise CodemodError(
                f"Codemod aborted: {len(errors)} file(s) failed py_compile. "
                f"All {len(snapshots)} file(s) rolled back to pre-codemod state.\n"
                f"Errors:\n{error_lines}"
            )

    return {"modified": modified, "skipped": skipped}
