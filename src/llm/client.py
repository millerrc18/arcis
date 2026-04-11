"""Ollama LLM client with graceful fallback.

Called by: data_collection.research_collector, llm.packet_writer, llm.postmortem_writer, llm.watchlist_writer, scheduler.premarket, scheduler.scorer, scheduler.vram_manager, scheduler.watch, services.system_service, training.ab_evaluation, training.dpo_pipeline, training.trainer
Calls: config, training.versioning
Owns tables: none
Config keys: base_url, enabled, llm, max_tokens, model, temperature, timeout_seconds
Tests: tests/test_llm_client.py
"""

import json
import logging
import re
import time

import requests

from src.config import load_config

logger = logging.getLogger(__name__)


def _get_llm_config() -> dict:
    """Load LLM config section with defaults.

    Checks the model versions table first — if a trained model is active,
    it takes precedence over the config file default.
    """
    config = load_config()
    llm_cfg = config.get("llm", {})

    model = llm_cfg.get("model", "qwen3:8b")
    try:
        from src.training.versioning import get_active_model_name
        active = get_active_model_name()
        if active and active != "base":
            model = active
    except Exception:
        pass  # Fall back to config model

    # #153: inference_timeout_seconds is the preferred key; fall back to
    # the legacy timeout_seconds, then to the 300s default.
    timeout = llm_cfg.get(
        "inference_timeout_seconds",
        llm_cfg.get("timeout_seconds", 300),
    )

    return {
        "enabled": llm_cfg.get("enabled", False),
        "model": model,
        "base_url": llm_cfg.get("base_url", "http://localhost:11434"),
        "temperature": llm_cfg.get("temperature", 0.7),
        "max_tokens": llm_cfg.get("max_tokens", 1500),
        "timeout_seconds": timeout,
    }


def is_llm_available() -> bool:
    """Check if Ollama is running and reachable.

    Returns True if reachable, False otherwise. Never raises.
    """
    try:
        cfg = _get_llm_config()
        resp = requests.get(f"{cfg['base_url']}/api/tags", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def _strip_think_blocks(text: str) -> str:
    """Remove <think>...</think> blocks from Qwen3 responses."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def generate(prompt: str, system_prompt: str, temperature: float | None = None,
             max_tokens: int | None = None) -> str | None:
    """Generate text using Ollama's OpenAI-compatible API.

    Args:
        prompt: The user message.
        system_prompt: The system message.
        temperature: Override temperature (default from config).
        max_tokens: Override max tokens (default from config).

    Returns:
        Generated text with think blocks stripped, or None on failure.
    """
    try:
        cfg = _get_llm_config()
        temp = temperature if temperature is not None else cfg["temperature"]
        tokens = max_tokens if max_tokens is not None else cfg["max_tokens"]

        t0 = time.monotonic()
        resp = requests.post(
            f"{cfg['base_url']}/v1/chat/completions",
            json={
                "model": cfg["model"],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temp,
                "max_tokens": tokens,
                "options": {
                    "repeat_penalty": 1.15,
                    "num_predict": tokens,
                },
            },
            timeout=cfg["timeout_seconds"],
        )
        resp.raise_for_status()
        elapsed = time.monotonic() - t0
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        content = _strip_think_blocks(content)
        # #167: treat empty / whitespace-only response as failure
        if not content or not content.strip():
            logger.warning("[LLM] Empty response from Ollama — treating as failure")
            return None
        logger.info("[LLM] Inference completed in %.1fs (%d chars)", elapsed, len(content))
        return content
    except Exception as e:
        logger.warning("[LLM] generate failed: %s", e)
        return None


def generate_structured(prompt: str, system_prompt: str, response_schema: dict,
                        temperature: float = 0.3) -> dict | None:
    """Generate structured JSON output using Ollama's OpenAI-compatible API.

    Args:
        prompt: The user message.
        system_prompt: The system message.
        response_schema: JSON schema for the expected response format.
        temperature: Temperature for generation (lower for structured output).

    Returns:
        Parsed JSON dict, or None on failure.
    """
    try:
        cfg = _get_llm_config()

        t0 = time.monotonic()
        resp = requests.post(
            f"{cfg['base_url']}/v1/chat/completions",
            json={
                "model": cfg["model"],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": response_schema,
                },
            },
            timeout=cfg["timeout_seconds"],
        )
        resp.raise_for_status()
        elapsed = time.monotonic() - t0
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        content = _strip_think_blocks(content)
        # #167: treat empty / whitespace-only response as failure
        if not content or not content.strip():
            logger.warning("[LLM] Empty structured response from Ollama — treating as failure")
            return None
        logger.info("[LLM] Structured inference completed in %.1fs", elapsed)
        return json.loads(content)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning("[LLM] Structured parse failed: %s", e)
        return None
    except Exception as e:
        logger.warning("[LLM] Structured generate failed: %s", e)
        return None
