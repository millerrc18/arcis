"""State query: Ollama model configuration.

Reads the configured model from settings.local.yaml rather than probing
the Ollama server (the probe belongs in a SystemEntry's health check).
Safe to call in any environment; returns config value or None.

Called by: src.platform.capability_registry.bootstrap (import-time side effect)
Calls: src.config.load_config
Owns tables: none
Config keys: llm.model, llm.host, llm.enabled, llm.temperature
Tests: tests/llm/test_ollama_state.py
"""
from __future__ import annotations

from datetime import date

from src.platform.capability_registry import register_state


def _ollama_config() -> dict:
    try:
        from src.config import load_config
        cfg = load_config()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"config unavailable: {exc}"}
    llm = (cfg or {}).get("llm", {}) or {}
    return {
        "value": {
            "model": llm.get("model"),
            "host": llm.get("host", "localhost:11434"),
            "enabled": bool(llm.get("enabled", True)),
            "temperature": llm.get("temperature"),
        },
    }


@register_state(
    name="ollama_model",
    description=(
        "Configured Ollama model + host. Currently halcyon-v1 (Qwen3 8B "
        "fine-tuned). Pairs with the ollama health check in the Systems "
        "registry to detect model-serving drift."
    ),
    category="llm",
    version="1.0",
    maintainer="ai_session",
    introduced_in="v0.12.0",
    last_reviewed_date=date(2026, 4, 18),
    refresh_hint="deploy-time",
)
def ollama_model() -> dict:
    return _ollama_config()
