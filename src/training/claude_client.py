"""Claude API client for generating training data.

Called by: council.protocol, evaluation.auditor, training.ab_evaluation, training.backfill, training.bootstrap, training.canary, training.curriculum, training.data_collector, training.quality_filter, training.trainer
Calls: config, training.versioning
Owns tables: none
Config keys: anthropic_api_key, api, training
Tests: tests/test_leakage_detector.py, tests/test_council_fail_closed.py
"""

import logging
import os

from src.config import load_config

logger = logging.getLogger(__name__)


# #612 — Typed exception for unrecoverable Anthropic outages so callers
# (data_collector, council/protocol) can fail-closed on auth/billing failures
# instead of silently returning None and synthesizing fake consensus.
class ClaudeAuthError(RuntimeError):
    """Raised when the Anthropic API rejects the request unrecoverably
    (credit_balance_too_low, authentication_error, invalid_api_key).
    Caller should halt the batch + alert operator, NOT retry per-item."""


_AUTH_ERROR_MARKERS = (
    "credit_balance_too_low",
    "authentication_error",
    "invalid_api_key",
    "invalid x-api-key",
)


def _get_anthropic_client(api_key: str):
    """Construct an Anthropic client. Extracted so tests can patch."""
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def _get_model_for_purpose(config: dict, purpose: str) -> str:
    """Resolve the Claude model to use based on task purpose.

    Priority: api.models.<task> → training.claude_model → Sonnet fallback.
    """
    api_models = config.get("api", {}).get("models", {})

    # Map purpose labels to config keys
    purpose_map = {
        "training_generation": "training_generation",
        "training_generation_anchor": "training_generation_anchor",
        "scoring": "quality_scoring",
        "quality_scoring": "quality_scoring",
        "council": "council_automated",
        "council_automated": "council_automated",
    }

    config_key = purpose_map.get(purpose)
    if config_key and config_key in api_models:
        return api_models[config_key]

    # Legacy fallback
    legacy = config.get("training", {}).get("claude_model", "")
    if legacy and legacy != "your-anthropic-api-key-here":
        return legacy

    return "claude-sonnet-4-20250514"


def _log_anthropic_cost_safely(message, purpose: str) -> None:
    """Best-effort api_costs write — never blocks the caller."""
    try:
        from src.training.versioning import log_api_cost
        log_api_cost(
            model=message.model,
            purpose=purpose,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )
    except Exception:
        pass


def _classify_anthropic_exception(exc: Exception) -> None:
    """#612 — Convert auth/billing failures to ClaudeAuthError so callers
    (data_collector, council) can halt + alert instead of silently
    retrying per-item. Transient errors (rate limit, 5xx, network) are
    left for the caller to swallow and continue."""
    err_str = str(exc).lower()
    if any(marker in err_str for marker in _AUTH_ERROR_MARKERS):
        logger.error("[CLAUDE] Unrecoverable auth/billing failure: %s", exc)
        raise ClaudeAuthError(str(exc)) from exc
    logger.warning("Claude API call failed: %s", exc)


def generate_training_example(
    system_prompt: str,
    user_prompt: str,
    purpose: str = "general",
    model_override: str | None = None,
) -> str | None:
    """Generate a training example via the Anthropic Claude API.

    Returns generated text, or None on transient failure. Raises
    ClaudeAuthError on unrecoverable auth/billing failures (#612).
    """
    try:
        import anthropic  # noqa: F401 — presence check
    except ImportError:
        logger.warning("anthropic package not installed. Run: pip install anthropic")
        return None

    config = load_config()
    api_key = os.environ.get("ANTHROPIC_API_KEY") or config.get("training", {}).get(
        "anthropic_api_key", ""
    )
    if not api_key or api_key == "your-anthropic-api-key-here":
        logger.warning("Anthropic API key not configured")
        return None

    model = model_override or _get_model_for_purpose(config, purpose)
    try:
        client = _get_anthropic_client(api_key)
        message = client.messages.create(
            model=model,
            max_tokens=1500,
            temperature=0.5,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        _log_anthropic_cost_safely(message, purpose)
        return message.content[0].text
    except ClaudeAuthError:
        raise  # already typed; propagate
    except Exception as exc:
        _classify_anthropic_exception(exc)
        return None
