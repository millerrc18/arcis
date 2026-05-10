"""Tests for scripts/verify_training_readiness.py.

Called by: test suite
Calls: scripts/verify_training_readiness
Owns tables: none
Config keys: none
Tests: self
"""
import json
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_verify():
    """Import the verify script as a module (adds scripts/ to sys.path)."""
    scripts_dir = str(Path(__file__).parent.parent / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import importlib
    if "verify_training_readiness" in sys.modules:
        return sys.modules["verify_training_readiness"]
    return importlib.import_module("verify_training_readiness")


# ---------------------------------------------------------------------------
# Test 1 — Check 1 fails without CUDA
# ---------------------------------------------------------------------------

def test_check_1_fails_without_cuda(monkeypatch):
    """_check_cuda() returns (False, msg) when torch.cuda.is_available() is False."""
    vtr = _import_verify()

    # Patch is_available to return False
    mock_cuda = MagicMock()
    mock_cuda.is_available.return_value = False

    mock_torch = MagicMock()
    mock_torch.cuda = mock_cuda

    monkeypatch.setattr(vtr, "torch", mock_torch, raising=False)

    ok, msg = vtr._check_cuda()
    assert ok is False
    assert "CUDA" in msg or "cuda" in msg.lower()


# ---------------------------------------------------------------------------
# Test 2 — Check 3 validates jsonl format (malformed line triggers failure)
# ---------------------------------------------------------------------------

def test_check_3_validates_jsonl_format(tmp_path):
    """_check_stage_files() returns (False, msg) when a file has a malformed line."""
    vtr = _import_verify()

    stage_file = tmp_path / "stage1_structure.jsonl"
    lines = [
        json.dumps({"instruction": "inst1", "input": "in1", "output": "out1"}),
        json.dumps({"instruction": "inst2", "input": "in2", "output": "out2"}),
        "NOT VALID JSON {{{",
    ]
    stage_file.write_text("\n".join(lines), encoding="utf-8")

    ok, msg = vtr._check_stage_files([str(stage_file)])
    assert ok is False
    assert "malformed" in msg.lower() or "invalid" in msg.lower() or "json" in msg.lower()


# ---------------------------------------------------------------------------
# Test 3 — Check 3 handles missing stage file (soft-warn, not hard failure)
# ---------------------------------------------------------------------------

def test_check_3_handles_missing_stage_file(tmp_path):
    """_check_stage_files() returns (True, ...) soft-warn when only a missing path given."""
    vtr = _import_verify()

    missing_path = str(tmp_path / "nonexistent_stage.jsonl")

    ok, msg = vtr._check_stage_files([missing_path])
    # Missing single stage = soft-warn; should NOT be a hard failure
    assert ok is True
    assert "MISSING" in msg or "missing" in msg.lower()


# ---------------------------------------------------------------------------
# Test 4 — main() exits non-zero when any check fails
# ---------------------------------------------------------------------------

def test_main_returns_nonzero_on_any_check_fail():
    """main() calls sys.exit with a non-zero code when Check 2 (deps) fails."""
    vtr = _import_verify()

    # Mock all five checks; check 2 fails
    check1_pass = (True, "CUDA OK")
    check2_fail = (False, "missing dep: bitsandbytes")
    check3_pass = (True, "stages OK")
    check4_pass = (True, "dry-run OK")
    check5_pass = (True, "GGUF OK")

    with (
        patch.object(vtr, "_check_cuda", return_value=check1_pass),
        patch.object(vtr, "_check_deps", return_value=check2_fail),
        patch.object(vtr, "_check_stage_files", return_value=check3_pass),
        patch.object(vtr, "_check_trainer_dry_run", return_value=check4_pass),
        patch.object(vtr, "_check_gguf", return_value=check5_pass),
        pytest.raises(SystemExit) as exc_info,
    ):
        vtr.main()

    assert exc_info.value.code != 0
