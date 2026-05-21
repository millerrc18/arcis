"""T7: assert vram_manager.py + handoff call sites are gone from src/.

Under dual-GPU separation there is no VRAM handoff: training runs on GPU0,
Ollama stays resident on GPU1. The vram_manager module and every
VRAMManager / handoff_to_training / handoff_to_inference reference must be
removed from the source tree (the obsolete TEST files are deleted later in
T10, so this only scans src/).
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"

_FORBIDDEN = re.compile(
    r"vram_manager|VRAMManager|handoff_to_training|handoff_to_inference"
)

# "Called by:" / "Calls:" header lines are module-cross-reference docstrings
# (e.g. config/__init__.py, training/versioning.py). They are NOT executable
# references; sweeping them is T8/T10 docstring hygiene, out of T7 scope.
_DOC_XREF = re.compile(r"^\s*(Called by|Calls):", re.IGNORECASE)


def test_vram_manager_module_deleted():
    assert not (_SRC / "scheduler" / "vram_manager.py").exists()


def test_no_vram_manager_references_in_src():
    offenders = []
    for path in _SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if _DOC_XREF.match(line):
                continue
            if _FORBIDDEN.search(line):
                offenders.append(f"{path.relative_to(_SRC)}:{lineno}: {line.strip()}")
    assert offenders == [], "leftover vram_manager references:\n" + "\n".join(offenders)


def test_scheduler_package_imports_cleanly():
    # Import-smoke: the deletion must not break the scheduler package.
    importlib.import_module("src.scheduler.watch")
    importlib.import_module("src.scheduler.overnight")
