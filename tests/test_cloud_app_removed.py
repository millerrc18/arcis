"""Phase 5 PR-B T8 — regression lock for src/api/cloud_app.py deletion.

Called by: pytest (Phase 5 §3.1 / PR-B T4-T8)
Calls: importlib
Owns tables: none
Config keys: none
Tests: that src/api/cloud_app.py is gone post-Render-decommission

Per Phase 5 unified design §3.1 (Render code sweep, #73): cloud_app.py
was the Render-hosted FastAPI entry point. The 2026-05-10 Cloudflare
cutover moved internet-facing traffic to src/api/app.py (lifting the
auth model verbatim — see app.py:18-22 docstring). Render PG was
decommissioned 2026-05-18 (memory: project_render_resources_stopped).
cloud_app.py was deleted in T4 (commit b7984155). This sentinel locks
the deletion so future merge conflicts don't accidentally re-introduce.

verify-by-mutation: this test FAILS if src/api/cloud_app.py is
re-created. Sabotage check: `touch src/api/cloud_app.py && pytest
tests/test_cloud_app_removed.py` should yield a FAIL (pytest.raises
does NOT raise because the import succeeds). Confirmed via dry-run
before this test was committed.
"""

from __future__ import annotations

import importlib

import pytest


def test_cloud_app_module_removed():
    """src/api/cloud_app.py was deleted in PR-B T4 — import must fail."""
    with pytest.raises(ImportError):
        importlib.import_module("src.api.cloud_app")
