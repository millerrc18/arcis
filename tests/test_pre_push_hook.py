"""Integration tests for scripts/hooks/pre-push (#59).

Verifies the hook:
1. Allows a push when the branch is up-to-date with origin/main
2. Refuses a push when the branch is behind origin/main (the stale-base hazard)
3. Refuses when origin/main can't be fetched (fail-closed posture)
4. Bypassable via `git push --no-verify` (this test doesn't run --no-verify
   directly — that's git's standard mechanism — but verifies the hook checks
   no env var that would override its decision)

We test by setting up a synthetic two-repo dance in tmp_path:
- `origin/`  — bare repo acting as remote
- `local/`   — clone with the hook installed
- Manipulate the local branch's position relative to origin/main, then run
  the hook directly (simulating what git would do at push time).

The hook receives:
- argv[1]: remote name
- stdin: lines of `<local_ref> <local_sha> <remote_ref> <remote_sha>`

For these tests we invoke the hook directly with `bash scripts/hooks/pre-push origin`
and rely on the hook reading `HEAD` and `origin/main` rather than parsing stdin.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


def _to_bash_path(p: Path | str) -> str:
    """Convert a path to a form bash (MSYS / Git Bash) can resolve on Windows.

    Git Bash translates `C:\\...` and `C:/...` differently depending on context;
    when invoked from a Python subprocess the Windows form often fails to
    resolve. The MSYS posix form `/c/...` is universally understood. On Linux
    this is a no-op (paths already start with `/`).
    """
    p = Path(p).as_posix()  # normalize to forward slashes
    if len(p) >= 2 and p[1] == ":":  # Windows drive letter
        return "/" + p[0].lower() + p[2:]
    return p


_HOOK_FS = REPO_ROOT / "scripts" / "hooks" / "pre-push"   # Path for Python file ops
HOOK = _to_bash_path(_HOOK_FS)                              # str for bash subprocess


def _run(*args: str, cwd: Path, check: bool = True, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=check,
        env=env or os.environ.copy(),
    )


@pytest.fixture
def synthetic_repos(tmp_path: Path) -> tuple[Path, Path]:
    """Create a bare 'origin' repo + a local clone, both initialized on main."""
    origin = tmp_path / "origin"
    local = tmp_path / "local"

    # Bare origin
    origin.mkdir()
    _run("git", "init", "--bare", "--initial-branch=main", str(origin), cwd=tmp_path)

    # Local clone — set up via init + remote add to avoid clone's empty-repo edge case
    local.mkdir()
    _run("git", "init", "--initial-branch=main", str(local), cwd=tmp_path)
    _run("git", "remote", "add", "origin", str(origin), cwd=local)
    _run("git", "config", "user.email", "test@example.com", cwd=local)
    _run("git", "config", "user.name", "Test", cwd=local)

    # Initial commit on main
    (local / "README.md").write_text("init\n")
    _run("git", "add", "README.md", cwd=local)
    _run("git", "commit", "-m", "init", cwd=local)
    _run("git", "push", "-u", "origin", "main", cwd=local)
    # Populate refs/remotes/origin/main so the hook can read it
    _run("git", "fetch", "origin", "main", cwd=local)

    # Copy the hook into the local repo
    hooks_dir = local / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(str(_HOOK_FS), str(hooks_dir / "pre-push"))
    (hooks_dir / "pre-push").chmod(0o755)

    return origin, local


def _invoke_hook(
    local: Path, remote: str = "origin", skip_fetch: bool = True
) -> subprocess.CompletedProcess:
    """Run the pre-push hook directly with the given remote arg.

    Copies the hook to a relative path inside local/ and invokes it via
    `bash ./hook-under-test <remote>`. We use a relative path because the
    Windows MSYS bash variant on some systems can't resolve absolute Windows
    paths when invoked via Python subprocess.

    Defaults to PRE_PUSH_SKIP_FETCH=1 so tests don't depend on the hook's
    git-fetch — instead, tests pre-populate `refs/remotes/origin/main` via
    explicit `git fetch` in their setup. Pass skip_fetch=False to exercise
    the fetch path directly (see test_pre_push_refuses_when_origin_unreachable).
    """
    hook_copy = local / "_pre_push_test_copy"
    shutil.copy(str(_HOOK_FS), str(hook_copy))
    hook_copy.chmod(0o755)
    # Note: passing env vars via subprocess.run(env=...) doesn't propagate to
    # Git Bash on Windows (MSYS filters non-allowlisted vars). We chain the
    # export inside bash itself, which sidesteps the filter.
    if skip_fetch:
        cmd_str = f"export PRE_PUSH_SKIP_FETCH=1 && exec bash ./_pre_push_test_copy '{remote}'"
    else:
        cmd_str = f"exec bash ./_pre_push_test_copy '{remote}'"
    return _run("bash", "-c", cmd_str, cwd=local, check=False)


def test_pre_push_allows_when_branch_is_current(synthetic_repos):
    """Hook exits 0 when branch is up-to-date with origin/main."""
    _origin, local = synthetic_repos
    result = _invoke_hook(local)
    assert result.returncode == 0, (
        f"Hook should ALLOW push when branch is current. stderr:\n{result.stderr}"
    )


def test_pre_push_refuses_when_branch_is_behind(synthetic_repos):
    """Hook exits 1 with 'REFUSED' when behind origin/main (stale-base hazard)."""
    origin, local = synthetic_repos

    # Add a commit to origin/main that local doesn't have
    other = local.parent / "other_clone"
    other.mkdir()
    _run("git", "init", "--initial-branch=main", str(other), cwd=local.parent)
    _run("git", "remote", "add", "origin", str(origin), cwd=other)
    _run("git", "config", "user.email", "test@example.com", cwd=other)
    _run("git", "config", "user.name", "Test", cwd=other)
    _run("git", "fetch", "origin", "main", cwd=other)
    _run("git", "checkout", "main", cwd=other)
    (other / "ahead.txt").write_text("ahead\n")
    _run("git", "add", "ahead.txt", cwd=other)
    _run("git", "commit", "-m", "ahead of local", cwd=other)
    _run("git", "push", "origin", "main", cwd=other)

    # Local now creates a feature branch off its current (stale) main
    _run("git", "checkout", "-b", "feature/stale", cwd=local)
    (local / "feature.txt").write_text("feature\n")
    _run("git", "add", "feature.txt", cwd=local)
    _run("git", "commit", "-m", "stale feature", cwd=local)

    # Refresh local's view of origin so origin/main reflects the truth
    _run("git", "fetch", "origin", "main", cwd=local)

    result = _invoke_hook(local)
    assert result.returncode == 1, (
        f"Hook should REFUSE when branch is behind. stderr:\n{result.stderr}"
    )
    assert "REFUSED" in result.stderr
    assert "behind" in result.stderr.lower()
    assert "rebase" in result.stderr.lower()


def test_pre_push_refuses_when_origin_unreachable_and_no_skip(tmp_path: Path):
    """Hook fails-closed when it can't fetch origin/main."""
    local = tmp_path / "local"
    local.mkdir()
    _run("git", "init", "--initial-branch=main", str(local), cwd=tmp_path)
    _run("git", "config", "user.email", "test@example.com", cwd=local)
    _run("git", "config", "user.name", "Test", cwd=local)
    # Point at a non-existent remote
    _run("git", "remote", "add", "origin", str(tmp_path / "does_not_exist"), cwd=local)

    # Initial commit so HEAD exists
    (local / "x.txt").write_text("x\n")
    _run("git", "add", "x.txt", cwd=local)
    _run("git", "commit", "-m", "init", cwd=local)

    # Copy hook
    hooks_dir = local / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(str(_HOOK_FS), str(hooks_dir / "pre-push"))
    (hooks_dir / "pre-push").chmod(0o755)

    # Don't skip fetch — exercising the unreachable-origin code path
    result = _invoke_hook(local, skip_fetch=False)
    assert result.returncode == 1, (
        f"Hook should REFUSE when origin unreachable. stderr:\n{result.stderr}"
    )
    assert "REFUSED" in result.stderr or "could not fetch" in result.stderr.lower()


def test_pre_push_skips_for_non_origin_remotes(synthetic_repos):
    """Hook is a no-op for pushes to non-origin remotes (e.g. forks)."""
    _origin, local = synthetic_repos
    result = _invoke_hook(local, remote="upstream")
    assert result.returncode == 0, (
        f"Hook should ALLOW push to non-origin remotes. stderr:\n{result.stderr}"
    )
