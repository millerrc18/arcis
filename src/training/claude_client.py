"""Claude API client for generating training data."""

import logging

from src.config import load_config

logger = logging.getLogger(__name__)


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
    api_key = training_cfg.get("anthropic_api_key", "")

    if not api_key or api_key == "your-anthropic-api-key-here":
        logger.warning("Anthropic API key not configured")
        return None

    model = model_override or _get_model_for_purpose(config, purpose)

    try:
        client = anthropic.Anthropic(api_key=api_key)
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
    except Exception as e:
        logger.warning("Claude API call failed: %s", e)
        return None
