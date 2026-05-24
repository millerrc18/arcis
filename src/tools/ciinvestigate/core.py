"""CIInvestigate core — gh run view wrapper with DA1 atomic cache + DA3 freshness.

Called by: src/tools/ciinvestigate/__main__.py, agent orchestrators
Calls: subprocess (gh CLI), json, os, pathlib, src.tools._safety.safe_op
Owns tables: none
Config keys: none (cache_dir defaults to data/cache/ci-investigate/)
Tests: tests/tools/test_ciinvestigate_integration.py

Cache flow (DA3):
  1. No cache file → full fetch. If completed, atomic-write cache. Return payload.
  2. Cache exists + clean JSON → head-check (lightweight). If updatedAt advanced
     or status not completed → full fetch + atomic-replace. Else return cached.
  3. Cache exists but corrupt JSON → WARNING + unlink + fall through to full fetch.
  4. no_cache=True → skip step 2/3 entirely, force full fetch.

Atomic write (DA1): tempfile + fsync + os.replace. No concurrency primitives.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Optional

from src.tools._safety import safe_op


logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CACHE_DIR = _REPO_ROOT / "data" / "cache" / "ci-investigate"

_FULL_FIELDS = (
    "conclusion,status,displayTitle,headBranch,headSha,createdAt,updatedAt,jobs"
)
_HEAD_FIELDS = "status,conclusion,updatedAt"


# ── Error ─────────────────────────────────────────────────────────────


class CIInvestigateError(RuntimeError):
    """Wraps gh missing, non-zero exit, JSON parse error, run-not-found."""


# ── Internal helpers ──────────────────────────────────────────────────


def _run_gh(run_id: int | str, fields: str, repo: Optional[str]) -> dict:
    """Call `gh run view <run_id> --json <fields>` and return parsed JSON.

    Raises:
        CIInvestigateError: gh not found, non-zero exit, JSON parse error.
    """
    cmd = ["gh", "run", "view", str(run_id), "--json", fields]
    if repo:
        cmd.extend(["-R", repo])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        raise CIInvestigateError(
            "gh CLI not found on PATH. "
            "Install gh via `winget install GitHub.cli` (Windows) "
            "or https://cli.github.com for other platforms."
        )
    except subprocess.TimeoutExpired as e:
        # Audit #105 T4 fix — spec contract is CIInvestigateError as the only
        # exception type. `from None` suppresses the original exception's
        # argv from chained traceback.
        raise CIInvestigateError(
            f"gh timed out after {e.timeout}s for run_id={run_id}"
        ) from None

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise CIInvestigateError(
            f"gh exited {result.returncode}: {stderr}"
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise CIInvestigateError(
            f"gh output not JSON: {e}; stdout={result.stdout[:200]}"
        )

    return payload


def _atomic_write(cache_path: Path, payload: dict) -> None:
    """Write payload to cache_path atomically: tempfile + fsync + os.replace.

    DA1 contract: three-step (flush + fsync + replace) is the entire
    concurrency story. Do NOT add threading.Lock or fcntl.flock here.

    The tmp filename is made unique per writer (pid + tid) so that
    concurrent writers on the same cache_path do not share a .tmp file
    and cause PermissionError on Windows NTFS during os.replace. Last
    writer wins (os.replace is atomic on both NTFS and POSIX).
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    unique = f"{os.getpid()}_{threading.get_ident()}"
    tmp_path = cache_path.with_name(f"{cache_path.stem}.{unique}.json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, cache_path)


def _read_cache(cache_path: Path) -> Optional[dict]:
    """Read cache file. Returns None if corrupt (and unlinks the file).

    DA1 self-heal: JSONDecodeError → WARNING + unlink + return None.
    """
    try:
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.warning(
            "corrupt cache %s: %s — deleting + refetching", cache_path, e
        )
        os.unlink(cache_path)
        return None


def _is_stale(head: dict, cached: dict) -> bool:
    """Return True if head-check indicates the cached payload is stale.

    Stale conditions:
      - head.status != 'completed' (run was re-triggered or is still running)
      - head.updatedAt > cached.updatedAt (run was re-run and conclusion changed)
    """
    if head.get("status") != "completed":
        return True
    head_updated = head.get("updatedAt", "")
    cached_updated = cached.get("updatedAt", "")
    return bool(head_updated and head_updated > cached_updated)


def _fetch_and_maybe_cache(
    run_id: int | str, repo: Optional[str], cache_path: Path
) -> dict:
    """Full fetch from gh. If completed, atomic-write cache. Return payload."""
    payload = _run_gh(run_id, _FULL_FIELDS, repo)
    if payload.get("conclusion"):
        _atomic_write(cache_path, payload)
    return payload


# ── Public API ────────────────────────────────────────────────────────


@safe_op(name="ciinvestigate", mutates=False)
def investigate(
    run_id: int | str,
    *,
    repo: Optional[str] = None,
    cache_dir: Optional[Path] = None,
    no_cache: bool = False,
) -> dict:
    """Fetch CI run details with cache + updatedAt-validated freshness.

    Args:
        run_id:    GitHub Actions run database ID (int or str).
        repo:      Optional OWNER/REPO override (passed as `gh -R`).
        cache_dir: Override cache directory (defaults to
                   data/cache/ci-investigate/ relative to repo root).
        no_cache:  If True, skip cache entirely and force a full fetch.

    Returns:
        dict with keys: conclusion, status, displayTitle, headBranch,
        headSha, createdAt, updatedAt, jobs.

    Raises:
        CIInvestigateError: gh not found, non-zero exit, JSON parse error,
                            or run-not-found.
    """
    resolved_cache_dir = Path(cache_dir) if cache_dir is not None else _DEFAULT_CACHE_DIR
    cache_path = resolved_cache_dir / f"{run_id}.json"

    if no_cache:
        return _fetch_and_maybe_cache(run_id, repo, cache_path)

    if not cache_path.exists():
        return _fetch_and_maybe_cache(run_id, repo, cache_path)

    # Cache exists — attempt to read it
    cached = _read_cache(cache_path)

    if cached is None:
        # Corrupt cache was unlinked — fall through to full fetch
        return _fetch_and_maybe_cache(run_id, repo, cache_path)

    # Lightweight head-check to validate freshness (DA3)
    head = _run_gh(run_id, _HEAD_FIELDS, repo)

    if _is_stale(head, cached):
        return _fetch_and_maybe_cache(run_id, repo, cache_path)

    return cached
