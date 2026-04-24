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


def generate_training_example(
    system_prompt: str,
    user_prompt: str,
    purpose: str = "general",
    model_override: str | None = None,
) -> str | None:
    """Generate a training example using the Anthropic Claude API.

    Args:
        system_prompt: System prompt for the generation.
        user_prompt: User prompt with feature/outcome data.
        purpose: Label for cost tracking and model selection
                 (e.g. "scoring", "training_generation", "training_generation_anchor").
        model_override: Explicit model to use (overrides config).

    Returns:
        Generated text, or None on failure.
    """
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed. Run: pip install anthropic")
        return None

    config = load_config()
    training_cfg = config.get("training", {})
    api_key = os.environ.get("ANTHROPIC_API_KEY") or training_cfg.get("anthropic_api_key", "")

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

        # Log cost (never blocks the caller)
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

        return message.content[0].text
    except ClaudeAuthError:
        raise  # already typed; propagate
    except Exception as e:
        # #612 — Classify auth/billing failures as unrecoverable so the caller
        # (data_collector, council) can halt + alert instead of silently
        # retrying per-item. Transient failures (rate limit, 5xx, network)
        # still return None so the batch can skip and continue.
        err_str = str(e).lower()
        if any(marker in err_str for marker in _AUTH_ERROR_MARKERS):
            logger.error("[CLAUDE] Unrecoverable auth/billing failure: %s", e)
            raise ClaudeAuthError(str(e)) from e
        logger.warning("Claude API call failed: %s", e)
        return None
