"""W21 P4-1 regression-lock: no test file should fall back from TEST_DATABASE_URL
to DATABASE_URL.

Background:
  The conftest docstring (added 2026-05-14 with P0 incident #158) noted
  ~24 test files used the broken fallback pattern:
    TEST_PG_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
  When DATABASE_URL points at the operator's local prod PG (port 5433)
  and TEST_DATABASE_URL is unset, fixtures in those files connect to
  production. This is the same path that caused P0 incident #159
  (2026-05-17 PG wipe — see CHANGELOG v0.36.14 entry).

  v0.36.14 added a pg_wrapper second-line defense that pytest.fails on
  prod TEST_DATABASE_URL. v0.36.19 (W21 P4-1) proactively swept the
  21 risky files to use ONLY TEST_DATABASE_URL — eliminating the
  noisy fallback even though the safety net catches it.

This regression-lock asserts the broken pattern doesn't return.

Allowed exceptions:
  - `tests/conftest.py` — references the pattern in a comment (the P0
    docstring warning about the legacy pattern). Acceptable as long as
    no actual code uses it.
  - `tests/test_conftest_pg_guard.py` — the guard's own regression
    tests; intentionally exercises the pattern.
"""

import re
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
_TESTS_DIR = _REPO_ROOT / "tests"

# The pattern (single-line OR multi-line) that fell back from TEST to prod.
_BROKEN_PATTERN = re.compile(
    r'os\.environ\.get\("TEST_DATABASE_URL"\)\s*or\s*os\.environ\.get\(\s*"DATABASE_URL"',
    flags=re.MULTILINE,
)

# Files allowed to reference the pattern (in comments or test fixtures
# intentionally exercising the guard).
_ALLOWED_FILES = {
    "tests/conftest.py",
    "tests/test_conftest_pg_guard.py",
    "tests/test_p4_1_fallback_pattern_gone.py",  # this file's own docstring
}


def test_no_broken_database_url_fallback_in_test_code():
    """No test file may use the `TEST_DATABASE_URL or DATABASE_URL` fallback
    in actual code paths. Files in the allowlist are exempt.
    """
    bad: list[tuple[str, int]] = []
    for path in _TESTS_DIR.rglob("*.py"):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel in _ALLOWED_FILES:
            continue
        source = path.read_text(encoding="utf-8")
        for match in _BROKEN_PATTERN.finditer(source):
            line_no = source[:match.start()].count("\n") + 1
            bad.append((rel, line_no))

    assert not bad, (
        "P4-1 regression: test files must NOT use the "
        "`TEST_DATABASE_URL or DATABASE_URL` fallback pattern. "
        "Use TEST_PG_URL = os.environ.get('TEST_DATABASE_URL', '') instead.\n"
        "Offenders:\n" + "\n".join(f"  {f}:{ln}" for f, ln in bad)
    )
