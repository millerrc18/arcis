"""AI Council agent registry and public exports.

Called by: council/context.py, council/protocol.py
Calls: council/agent_data.py, council/prompts.py
Owns tables: none
Config keys: none
Tests: tests/test_council.py
"""

from src.council.agent_data import (
    _query_db,
    gather_innovation_data,
    gather_macro_data,
    gather_risk_data,
    gather_strategic_data,
    gather_tactical_data,
)
from src.council.prompts import AGENT_NAMES, AGENT_PROMPTS

AGENT_DATA_FUNCTIONS = {
    "tactical_operator": gather_tactical_data,
    "strategic_architect": gather_strategic_data,
    "red_team": gather_risk_data,
    "innovation_engine": gather_innovation_data,
    "macro_navigator": gather_macro_data,
}
