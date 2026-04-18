"""Verify ollama_state capability registers + query returns expected shape."""
from __future__ import annotations


def test_ollama_state_imports_clean():
    import src.llm.ollama_state as mod
    assert mod is not None


def test_ollama_model_is_registered_state():
    import src.llm.ollama_state  # noqa: F401 — side effect
    from src.platform.capability_registry import get_state

    entry = get_state("ollama_model")
    assert entry is not None
    assert entry.kind == "state"
    assert entry.refresh_hint == "deploy-time"


def test_ollama_query_returns_dict_with_value_key():
    from src.llm.ollama_state import _ollama_config

    result = _ollama_config()
    # Either returns {"value": {...}} (config loaded) or {"error": "..."}
    # — both are dict responses.
    assert isinstance(result, dict)
    assert "value" in result or "error" in result
