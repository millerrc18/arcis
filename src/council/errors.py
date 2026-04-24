"""Council exception types (#612).

Defined in a separate module to avoid import cycles between aggregation,
engine, and protocol modules.
"""


class CouncilUnavailableError(RuntimeError):
    """Raised when council aggregation cannot synthesize a real consensus
    because every agent vote was a parse-failure stub.

    Pre-#612, `aggregate_votes` silently fell back to using the failed-stub
    assessments and emitted a synthesized "5-0 neutral consensus" that drove
    risk-knob clipping for two trading days during the 4/21–4/22 Anthropic
    billing outage. Fail-closed prevents the autonomous trading system from
    making risk decisions based on a fabricated consensus."""
