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
    except Exception as exc:
        # #601 — Don't silently swallow active-model lookup failures; debug-log
        # so the operator can see when versioning state is broken.
        logger.debug("[LLM] active model lookup failed; using config default %s: %s", model, exc)

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


# #388: Track consecutive failures to avoid burning 180s timeouts
# when Ollama is down. Reset on success.
_consecutive_failures = 0
_MAX_CONSECUTIVE_FAILURES = 3


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


def get_loaded_model_name() -> str:
    """Return the name of the currently-loaded Ollama model.

    Queries ``/api/ps`` for the running model. Falls back to the config's
    ``llm.model`` value when Ollama is unreachable. Returns ``"unknown"`` only
    when both sources fail. Used by training.versioning.get_active_model_name
    as a fallback when model_versions has no active row — the DB may be empty
    on a cloud deployment while Ollama still reports the correct model locally.

    Does not consult the model_versions table to avoid recursion with the
    caller.
    """
    try:
        config = load_config()
        llm_cfg = config.get("llm", {})
        base_url = llm_cfg.get("base_url", "http://localhost:11434")
        resp = requests.get(f"{base_url}/api/ps", timeout=3)
        if resp.status_code == 200:
            models = (resp.json() or {}).get("models") or []
            if models and models[0].get("name"):
                return models[0]["name"]
        cfg_model = llm_cfg.get("model")
        if cfg_model:
            return cfg_model
    except Exception as exc:
        logger.debug("get_loaded_model_name failed: %s", exc)
    return "unknown"


def _check_ollama_health_or_restart() -> bool:
    """Check Ollama health; fail soft if unresponsive.

    After 3+ consecutive inference failures, this function is called before
    the next attempt. Returns True if Ollama is healthy. On unhealthy, logs
    that ArcisOllamaWatchdog owns recovery and returns False (fail soft).

    The unpinned subprocess.Popen self-restart was removed: it could spawn
    Ollama on GPU0 and collide with training under the dual-GPU partition.
    ArcisOllamaWatchdog's 30s loop is the single Ollama recovery owner.
    """
    if is_llm_available():
        return True

    logger.warning(
        "[LLM] Ollama unresponsive — ArcisOllamaWatchdog owns recovery (30s loop); failing soft"
    )
    return False


def _strip_think_blocks(text: str) -> str:
    """Remove <think>...</think> blocks from Qwen3 responses."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def generate(prompt: str, system_prompt: str, temperature: float | None = None,
             max_tokens: int | None = None, batch_mode: bool = False) -> str | None:
    """Generate text using Ollama's OpenAI-compatible API.

    Args:
        prompt: The user message.
        system_prompt: The system message.
        temperature: Override temperature (default from config).
        max_tokens: Override max tokens (default from config).
        batch_mode: When True, skip the 2s post-call cooldown that exists for
            #388 (Ollama overload protection during scan cycles). The corpus
            runner sets this so the per-call cooldown doesn't compound across
            ThreadPoolExecutor workers; the live-scan path leaves it False
            so the #388 protection still fires.

    Returns:
        Generated text with think blocks stripped, or None on failure.
    """
    global _consecutive_failures

    # #388: Skip immediately if Ollama has been failing repeatedly
    if _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
        if not _check_ollama_health_or_restart():
            logger.warning("[LLM] Skipping inference — Ollama down after %d consecutive failures",
                           _consecutive_failures)
            return None
        _consecutive_failures = 0  # Reset after successful restart

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
        _consecutive_failures = 0
        # #388: Brief cooldown between calls to prevent Ollama overload
        # during batch processing (scan cycles hit 10-20 tickers in sequence).
        # 2s is enough for Ollama to release KV cache from the prior request.
        # #108 Lever 1: corpus-runner callers pass batch_mode=True to skip this
        # cooldown — N-way parallel dispatch already smooths the request rate,
        # and stacking the 2s sleep on every parallel worker would erase a
        # large fraction of the parallelism speedup. Live-scan callers leave
        # batch_mode=False so #388 protection still fires.
        if not batch_mode:
            time.sleep(2)
        return content
    except Exception as e:
        _consecutive_failures += 1
        logger.warning("[LLM] generate failed (failure %d/%d): %s",
                       _consecutive_failures, _MAX_CONSECUTIVE_FAILURES, e)
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
    global _consecutive_failures

    # #388 follow-up: circuit breaker for structured generation too
    if _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
        if not _check_ollama_health_or_restart():
            logger.warning("[LLM] Skipping structured inference — Ollama down after %d failures",
                           _consecutive_failures)
            return None
        _consecutive_failures = 0

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
        _consecutive_failures = 0
        return json.loads(content)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning("[LLM] Structured parse failed: %s", e)
        return None
    except Exception as e:
        _consecutive_failures += 1
        logger.warning("[LLM] Structured generate failed (failure %d/%d): %s",
                       _consecutive_failures, _MAX_CONSECUTIVE_FAILURES, e)
        return None
