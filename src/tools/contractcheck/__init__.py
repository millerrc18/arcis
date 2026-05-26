"""ContractCheck v1 — record/verify/diff baselines for pinned CLI invocations.

Purpose: Surface drift in external-CLI invocations (argv shape + parsed output)
         that production code depends on. v1 pins the watchloop's nvidia-smi call.

Called by: operator agents, python -m src.tools.contractcheck, tests
Calls: src.tools.contractcheck.core
Owns tables: none
Config keys: contracts (arcis_config.yaml)
Tests: tests/tools/test_contractcheck.py (T6)
"""

from .core import diff, record, verify

__all__ = ["record", "verify", "diff"]
