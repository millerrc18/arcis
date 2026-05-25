# Purpose: CapabilityRegistryQuery subpackage — read-only inspection of TABLES registry.
# Called by: operator agents, src/tools/capabilityregistry/__main__.py
# Calls: src.tools.capabilityregistry.core
# Owns tables: none
# Config keys: none
# Tests: tests/tools/test_capabilityregistry_integration.py

from src.tools.capabilityregistry.core import CapabilityRegistryError, table, tables

__all__ = ["tables", "table", "CapabilityRegistryError"]
