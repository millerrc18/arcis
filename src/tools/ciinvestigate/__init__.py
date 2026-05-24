# Purpose: CIInvestigate subpackage public API — expose investigate + CIInvestigateError.
# Called by: agent orchestrators, src/tools/ciinvestigate/__main__.py
# Calls: src.tools.ciinvestigate.core
# Owns tables: none
# Config keys: none
# Tests: tests/tools/test_ciinvestigate_integration.py
"""CIInvestigate — GitHub Actions run introspection with atomic-write cache.

Public surface:
  investigate(run_id, *, repo, cache_dir, no_cache) -> dict
  CIInvestigateError(RuntimeError)
"""

from src.tools.ciinvestigate.core import CIInvestigateError, investigate

__all__ = ["investigate", "CIInvestigateError"]
