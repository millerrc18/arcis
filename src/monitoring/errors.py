"""Monitoring exception types (C4 / #45).

Called by: src/monitoring/manual_intervention_drift.py
Calls: none
Owns tables: none
Config keys: none
Tests: tests/monitoring/test_manual_intervention_drift.py
"""


class MonitoringError(Exception):
    """Base class for all monitoring exceptions."""


class MonitoringDataError(MonitoringError):
    """Raised when a broker or DB read fails inside the drift detector."""
