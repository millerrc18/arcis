"""Regression-lock for v0.36.35 issue B — Ollama executable full-path resolution.

After a failed VRAM handoff, the manager restarts Ollama via
`subprocess.Popen(["ollama", "serve"])`. Under the NSSM service context the
operator's user PATH is absent, so this raised `[WinError 2] cannot find the
file specified` (observed 2026-05-19 18:54) — Ollama never came back from the
handoff path. Fix: resolve the executable up front (`_find_ollama`) and use the
resolved path at every invocation, falling back to PATH lookup only if not
found at a known location.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import src.scheduler.vram_manager as vm_mod


def test_find_ollama_prefers_path_lookup():
    with patch("shutil.which", return_value=r"C:\on\path\ollama.exe"):
        assert vm_mod._find_ollama() == r"C:\on\path\ollama.exe"


def test_find_ollama_falls_back_to_localappdata():
    fake = r"C:\Users\mille\AppData\Local\Programs\Ollama\ollama.exe"
    with patch("shutil.which", return_value=None), \
         patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\mille\AppData\Local"}), \
         patch("os.path.isfile", side_effect=lambda p: p == fake):
        assert vm_mod._find_ollama() == fake


def test_find_ollama_none_when_absent():
    with patch("shutil.which", return_value=None), \
         patch("os.path.isfile", return_value=False):
        assert vm_mod._find_ollama() is None


def test_manager_resolves_ollama_path_on_init():
    resolved = r"C:\Users\mille\AppData\Local\Programs\Ollama\ollama.exe"
    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value=None), \
         patch("src.scheduler.vram_manager._find_ollama", return_value=resolved):
        vm = vm_mod.VRAMManager()
    assert vm._ollama == resolved


def test_manager_falls_back_to_bare_name_when_unresolved():
    """When _find_ollama returns None, fall back to bare 'ollama' (PATH lookup
    at call time) so behavior is unchanged on hosts where it IS on PATH."""
    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value=None), \
         patch("src.scheduler.vram_manager._find_ollama", return_value=None):
        vm = vm_mod.VRAMManager()
    assert vm._ollama == "ollama"
