"""Phase 5 PR-B T8 — regression lock for DATABASE_URL strip from cloud_routes/.

Called by: pytest (Phase 5 §3.2 / PR-B T6-T8)
Calls: stdlib pathlib (re-walks cloud_routes)
Owns tables: none
Config keys: none
Tests: that no src/api/cloud_routes/*.py file references DATABASE_URL

Per Phase 5 unified design §3.2 (Render code sweep, #73): the
DATABASE_URL env var was the gate for the Render-PG branches in
cloud_routes/*.py. Render PG offline 2026-05-18 (memory:
project_render_resources_stopped). T6 (commit 2abe0fcb) stripped
the 4 batch-1 files (platform, broker_exceptions, commands,
kpis_compute); T7 (commit bdde5cf9) stripped the 3 batch-2 files
(notifications, preflight, walkforward) + cleaned __init__.py
docstring. This sentinel locks the invariant: zero DATABASE_URL
references in any cloud_routes module.

verify-by-mutation: this test FAILS if a future change re-adds
DATABASE_URL gating to any cloud_routes/*.py. Sabotage check:
`echo 'os.environ.get("DATABASE_URL", "")' >> src/api/cloud_routes/
platform.py && pytest tests/test_no_database_url_branch.py` must
yield FAIL. Confirmed via dry-run before this test was committed.
"""

from __future__ import annotations

import pathlib

import pytest


CLOUD_ROUTES_DIR = pathlib.Path(__file__).resolve().parent.parent / "src" / "api" / "cloud_routes"


def test_no_database_url_in_any_cloud_route_module():
    """No src/api/cloud_routes/*.py file may reference DATABASE_URL."""
    offenders: list[str] = []
    for py_file in CLOUD_ROUTES_DIR.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        if "DATABASE_URL" in text:
            # Find the offending line numbers for actionable failure output
            for line_num, line in enumerate(text.splitlines(), start=1):
                if "DATABASE_URL" in line:
                    offenders.append(f"{py_file.name}:{line_num}: {line.rstrip()}")
    assert not offenders, (
        "DATABASE_URL re-introduced into cloud_routes/ (Phase 5 PR-B T6-T7 strip violated):\n"
        + "\n".join(offenders)
    )
