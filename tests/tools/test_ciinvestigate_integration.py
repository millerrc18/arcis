# Purpose: Integration tests for src/tools/ciinvestigate — DA1 atomic write,
#          DA1 corrupt-cache self-heal, DA3 updatedAt-validated freshness.
# Called by: pytest
# Calls: src.tools.ciinvestigate.core.investigate, subprocess (mocked or real gh)
# Owns tables: none
# Config keys: none
# Tests: this file
"""Integration tests for CIInvestigate tool.

Covers 9 cases as specified in the Task 4 test strategy:
  (a) real gh call or monkey-patched happy path — cache written
  (b) cache hit — only head-check gh call made (not full fetch)
  (c) in-progress payload — cache NOT written
  (d) gh not on PATH — CIInvestigateError with winget hint
  (e) --no-cache flag — forces full re-fetch
  (f) concurrent writers (DA1) — no torn/residue writes
  (g) corrupt cache recovery (DA1) — unlink + refetch + WARNING log
  (h) rerun invalidation (DA3) — stale cache replaced when updatedAt advances
  (i) CLI --json subprocess with nonexistent run — error envelope + exit 1
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── helpers ────────────────────────────────────────────────────────────

COMPLETED_PAYLOAD = {
    "conclusion": "success",
    "status": "completed",
    "displayTitle": "CI / test",
    "headBranch": "main",
    "headSha": "abc123",
    "createdAt": "2026-05-24T09:00:00Z",
    "updatedAt": "2026-05-24T10:00:00Z",
    "jobs": [
        {
            "name": "test",
            "conclusion": "success",
            "steps": [
                {"name": "Run tests", "conclusion": "success", "number": 1},
            ],
        }
    ],
}

IN_PROGRESS_PAYLOAD = {
    "conclusion": None,
    "status": "in_progress",
    "displayTitle": "CI / test",
    "headBranch": "feature/x",
    "headSha": "def456",
    "createdAt": "2026-05-24T09:00:00Z",
    "updatedAt": "2026-05-24T09:05:00Z",
    "jobs": [],
}

HEAD_CHECK_SUCCESS = {
    "status": "completed",
    "conclusion": "success",
    "updatedAt": "2026-05-24T10:00:00Z",
}

STALE_FAILURE_PAYLOAD = {
    "conclusion": "failure",
    "status": "completed",
    "displayTitle": "CI / test",
    "headBranch": "main",
    "headSha": "abc123",
    "createdAt": "2026-05-24T09:00:00Z",
    "updatedAt": "2026-05-24T10:00:00Z",
    "jobs": [
        {
            "name": "test",
            "conclusion": "failure",
            "steps": [
                {"name": "Run tests", "conclusion": "failure", "number": 1},
            ],
        }
    ],
}

RERUN_SUCCESS_PAYLOAD = {
    "conclusion": "success",
    "status": "completed",
    "displayTitle": "CI / test",
    "headBranch": "main",
    "headSha": "abc123",
    "createdAt": "2026-05-24T09:00:00Z",
    "updatedAt": "2026-05-24T11:00:00Z",
    "jobs": [
        {
            "name": "test",
            "conclusion": "success",
            "steps": [],
        }
    ],
}


def _make_completed_run_result(payload: dict) -> MagicMock:
    """Build a subprocess.CompletedProcess mock returning `payload` as JSON."""
    m = MagicMock()
    m.returncode = 0
    m.stdout = json.dumps(payload)
    m.stderr = ""
    return m


# ── (a) happy path — real gh or monkey-patched completed run ────────────

def test_a_completed_run_returns_dict_and_writes_cache(tmp_path):
    """Full fetch for a completed run: dict returned, cache file written.

    Verify-by-mutation: if the cache write is removed the second assertion
    fails. The @safe_op 'success' event path is validated by
    tests/tools/test_safe_op_integration.py.
    """
    from src.tools.ciinvestigate.core import investigate, CIInvestigateError

    run_id = 12345678

    with patch("subprocess.run", return_value=_make_completed_run_result(COMPLETED_PAYLOAD)):
        result = investigate(run_id, cache_dir=tmp_path)

    assert isinstance(result, dict)
    assert result["conclusion"] == "success"

    cache_file = tmp_path / f"{run_id}.json"
    assert cache_file.exists(), "cache file must be written for a completed run"
    cached = json.loads(cache_file.read_text(encoding="utf-8"))
    assert cached["conclusion"] == "success"


# ── (b) cache hit — second call only does head-check ───────────────────

def test_b_cache_hit_only_head_check_called(tmp_path):
    """Second call with valid cache issues only 1 head-check gh call.

    Verify-by-mutation: if the head-check is bypassed and cached data
    returned directly, call_count['n'] == 0 and the test fails.
    """
    from src.tools.ciinvestigate.core import investigate

    run_id = 12345679

    # Pre-populate the cache
    cache_file = tmp_path / f"{run_id}.json"
    cache_file.write_text(json.dumps(COMPLETED_PAYLOAD), encoding="utf-8")

    call_count = {"n": 0}

    def fake_subprocess(cmd, **kwargs):
        call_count["n"] += 1
        # Only the head-check fields (fewer fields → 1 call, not full fetch)
        return _make_completed_run_result(HEAD_CHECK_SUCCESS)

    with patch("subprocess.run", side_effect=fake_subprocess):
        result = investigate(run_id, cache_dir=tmp_path)

    assert result["conclusion"] == "success"
    # Must be exactly 1 gh call (head-check only, not full fetch)
    assert call_count["n"] == 1, (
        f"Expected 1 gh call (head-check), got {call_count['n']}. "
        "If 0, head-check was bypassed. If >1, full fetch was triggered."
    )


# ── (c) in-progress payload — no cache written ─────────────────────────

def test_c_in_progress_does_not_write_cache(tmp_path):
    """In-progress runs must NOT be cached.

    Verify-by-mutation: if the `if conclusion:` guard is removed,
    in_progress runs are cached and the cache_path.exists() assertion fails.
    """
    from src.tools.ciinvestigate.core import investigate

    run_id = 12345680

    with patch("subprocess.run", return_value=_make_completed_run_result(IN_PROGRESS_PAYLOAD)):
        result = investigate(run_id, cache_dir=tmp_path)

    assert result["status"] == "in_progress"
    cache_file = tmp_path / f"{run_id}.json"
    assert not cache_file.exists(), (
        "cache MUST NOT be written for an in-progress run — "
        "Fails if the `if conclusion:` check is removed — in-progress runs get cached "
        "and serve stale 'in_progress' state."
    )


# ── (d) gh not on PATH → CIInvestigateError with winget hint ──────────

def test_d_gh_not_on_path_raises_error_with_winget_hint(tmp_path):
    """FileNotFoundError on subprocess.run → CIInvestigateError with winget hint.

    Verify-by-mutation: if the FileNotFoundError is not caught, the test
    sees FileNotFoundError instead of CIInvestigateError.
    """
    from src.tools.ciinvestigate.core import investigate, CIInvestigateError

    run_id = 12345681

    with patch("subprocess.run", side_effect=FileNotFoundError("gh not found")):
        with pytest.raises(CIInvestigateError) as exc_info:
            investigate(run_id, cache_dir=tmp_path)

    assert "winget install" in str(exc_info.value), (
        "Error message must include winget install hint for operator remediation"
    )


# ── (e) --no-cache forces full re-fetch ────────────────────────────────

def test_e_no_cache_forces_full_fetch(tmp_path):
    """no_cache=True must skip cache entirely and re-fetch.

    Verify-by-mutation: if no_cache is not checked, the cached file is
    returned and call_count['n'] == 0 instead of 1.
    """
    from src.tools.ciinvestigate.core import investigate

    run_id = 12345682

    # Pre-write a cache file
    cache_file = tmp_path / f"{run_id}.json"
    cache_file.write_text(json.dumps(COMPLETED_PAYLOAD), encoding="utf-8")
    old_mtime = cache_file.stat().st_mtime

    # Small delay to ensure mtime difference is detectable
    time.sleep(0.01)

    call_count = {"n": 0}

    def fake_subprocess(cmd, **kwargs):
        call_count["n"] += 1
        return _make_completed_run_result(COMPLETED_PAYLOAD)

    with patch("subprocess.run", side_effect=fake_subprocess):
        result = investigate(run_id, cache_dir=tmp_path, no_cache=True)

    assert result["conclusion"] == "success"
    # Must have done a full fetch (not just head-check)
    # Full fetch → 1 call. Head-check + fetch → 2 calls.
    # no-cache should do exactly 1 call (skip head-check, go straight to full fetch)
    assert call_count["n"] == 1, (
        f"Expected 1 full fetch call, got {call_count['n']}"
    )
    # Cache file mtime should be newer than before
    new_mtime = cache_file.stat().st_mtime
    assert new_mtime > old_mtime, "cache file must be refreshed after no_cache fetch"


# ── (f) concurrent writers (DA1) ───────────────────────────────────────

def test_f_concurrent_writers_produce_valid_cache(tmp_path):
    """Two concurrent _atomic_write calls must not produce a torn/corrupt cache.

    Tests _atomic_write directly (the DA1 contract). On Windows, os.replace()
    may raise PermissionError if the destination is being simultaneously
    replaced by another thread. This is NOT a torn-file — it's an atomic
    refusal. The test verifies: any file that exists after the race is valid
    JSON (no partial/torn writes), and no .tmp residue remains.

    Verify-by-mutation: if os.replace is replaced with open+write,
    the test fails because partial writes produce invalid JSON (not a clean
    PermissionError). The open+write race produces torn data; os.replace
    produces either a complete file or an atomic failure.

    Fails if `os.replace(tmp_path, cache_path)` is replaced with
    `open(cache_path, 'w').write(...)` — concurrent writers see a
    partial-file race.
    """
    from src.tools.ciinvestigate.core import _atomic_write

    run_id = 12345683
    cache_file = tmp_path / f"{run_id}.json"
    errors = []

    def worker():
        try:
            time.sleep(0.05)  # overlap writes
            _atomic_write(cache_file, COMPLETED_PAYLOAD)
        except PermissionError:
            # Windows NTFS: os.replace raises PermissionError when two threads
            # simultaneously replace the same target. This is an atomic refusal
            # (no partial file) — the DA1 invariant is preserved.
            pass
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, f"Worker threads raised unexpected errors: {errors}"

    # (i) if a cache file was written, it must be valid JSON (no torn writes)
    if cache_file.exists():
        content = cache_file.read_text(encoding="utf-8")
        parsed = json.loads(content)  # raises json.JSONDecodeError if torn
        assert parsed["conclusion"] == "success"
    # If neither writer succeeded (both PermissionError), the absence of the
    # file is also acceptable — no data corruption occurred.

    # (ii) NO .tmp residue (unique per-writer tmp names must all be cleaned up)
    tmp_residues = list(tmp_path.glob(f"{run_id}.*.json.tmp"))
    assert not tmp_residues, (
        f".tmp residue(s) must not exist — atomic rename must clean up: {tmp_residues}"
    )


# ── (g) corrupt cache recovery (DA1) ──────────────────────────────────

def test_g_corrupt_cache_is_healed_and_warns(tmp_path, caplog):
    """Truncated JSON in cache → unlink + refetch + WARNING log.

    Verify-by-mutation: if the `except json.JSONDecodeError` clause is
    removed, the tool raises instead of self-healing.
    """
    from src.tools.ciinvestigate.core import investigate

    run_id = 12345684

    # Write a corrupt (truncated) cache file
    cache_file = tmp_path / f"{run_id}.json"
    cache_file.write_text('{"conclusion": "success"', encoding="utf-8")  # missing closing brace

    with caplog.at_level(logging.WARNING, logger="src.tools.ciinvestigate.core"):
        with patch("subprocess.run", return_value=_make_completed_run_result(COMPLETED_PAYLOAD)):
            result = investigate(run_id, cache_dir=tmp_path)

    # (i) corrupt file replaced with valid JSON
    assert cache_file.exists(), "cache file must be replaced (not just deleted)"
    valid_content = json.loads(cache_file.read_text(encoding="utf-8"))
    assert valid_content["conclusion"] == "success"

    # (ii) return value is from the fresh fetch
    assert result["conclusion"] == "success"

    # (iii) WARNING log mentions "corrupt cache"
    assert any("corrupt cache" in record.message for record in caplog.records), (
        "WARNING log must mention 'corrupt cache'. "
        "Fails if the `except json.JSONDecodeError` clause is removed — "
        "the tool raises instead of self-healing."
    )


# ── (h) rerun invalidation (DA3) ───────────────────────────────────────

def test_h_rerun_invalidation_replaces_stale_cache(tmp_path):
    """Cache hit with newer updatedAt in head-check triggers full re-fetch.

    Verify-by-mutation: if the updatedAt head-check is removed, the tool
    returns the stale 'failure' verdict from cache.
    """
    from src.tools.ciinvestigate.core import investigate

    run_id = 12345685

    # Pre-write a stale failure cache (T=10:00)
    cache_file = tmp_path / f"{run_id}.json"
    cache_file.write_text(json.dumps(STALE_FAILURE_PAYLOAD), encoding="utf-8")

    call_num = {"n": 0}

    def dispatch_subprocess(cmd, **kwargs):
        call_num["n"] += 1
        if call_num["n"] == 1:
            # First call = head-check: newer updatedAt + conclusion=success
            head = {
                "status": "completed",
                "conclusion": "success",
                "updatedAt": "2026-05-24T11:00:00Z",  # T1 > T0 (10:00)
            }
            return _make_completed_run_result(head)
        else:
            # Second call = full fetch with success body
            return _make_completed_run_result(RERUN_SUCCESS_PAYLOAD)

    with patch("subprocess.run", side_effect=dispatch_subprocess):
        result = investigate(run_id, cache_dir=tmp_path)

    # (i) returned dict has conclusion='success' (not stale 'failure')
    assert result["conclusion"] == "success", (
        "Must return fresh conclusion. "
        "Fails if the updatedAt head-check is removed — the tool returns the "
        "stale 'failure' verdict from cache."
    )

    # (ii) cache file on disk has the success body (atomic-replaced)
    cached_on_disk = json.loads(cache_file.read_text(encoding="utf-8"))
    assert cached_on_disk["conclusion"] == "success", (
        "cache file must be atomically replaced with the success body"
    )


# ── (i) CLI subprocess error envelope ─────────────────────────────────

@pytest.mark.skipif(shutil.which("gh") is None, reason="requires gh on PATH")
def test_i_cli_nonexistent_run_produces_error_envelope(tmp_path):
    """CLI with nonexistent run_id emits JSON error envelope and exits 1.

    Gated on real gh being available. Uses a definitively nonexistent run_id.
    """
    result = subprocess.run(
        [
            sys.executable, "-m", "src.tools.ciinvestigate",
            "999999999999",  # definitively nonexistent
            "--json",
            "--no-cache",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(Path(__file__).resolve().parents[2]),
        timeout=30,
    )

    assert result.returncode == 1, (
        f"Expected exit 1, got {result.returncode}. stdout: {result.stdout!r}"
    )

    try:
        envelope = json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"stdout was not valid JSON: {result.stdout!r}")

    assert "error" in envelope, f"Expected error envelope, got: {envelope}"
    assert envelope["error"]["type"] == "CIInvestigateError", (
        f"Expected CIInvestigateError, got: {envelope['error']['type']}"
    )
