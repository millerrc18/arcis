"""Oracle subpackage for the lifecycle simulator.

Houses the anti-masking machinery that lets the simulator distinguish
"degraded correctly" from "error silently swallowed". Task 9 consumes
these observers to assert fail-conservative invariants.
"""

from src.simulation.lifecycle.oracle.capital import CapitalLedger
from src.simulation.lifecycle.oracle.error_observer import SwallowedErrorObserver
from src.simulation.lifecycle.oracle.invariants import InvariantResult, Oracle

__all__ = ["CapitalLedger", "SwallowedErrorObserver", "Oracle", "InvariantResult"]
