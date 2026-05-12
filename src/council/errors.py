"""Council exception types (#612, #68).

Called by: council.aggregation, council.engine, council.protocol, council.agent_data
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_council_fail_closed.py, tests/council/test_typed_errors.py

Defined in a separate module to avoid import cycles between aggregation,
engine, and protocol modules.
"""


class CouncilError(Exception):
    """Base class for all council exceptions (#68)."""


class CouncilParseError(CouncilError):
    """Raised when a JSON or response parse fails in a council context."""


class CouncilTimeoutError(CouncilError):
    """Raised when an LLM or agent operation times out."""


class CouncilAgentDataError(CouncilError):
    """Raised when a DB or data-fetch operation fails in agent_data."""


class CouncilProviderError(CouncilError):
    """Raised when an external provider (LLM, HTTP) call fails."""


class CouncilUnavailableError(RuntimeError, CouncilError):
    """Raised when council aggregation cannot synthesize a real consensus
    because every agent vote was a parse-failure stub.

    Pre-#612, `aggregate_votes` silently fell back to using the failed-stub
    assessments and emitted a synthesized "5-0 neutral consensus" that drove
    risk-knob clipping for two trading days during the 4/21–4/22 Anthropic
    billing outage. Fail-closed prevents the autonomous trading system from
    making risk decisions based on a fabricated consensus."""
