"""Grammar-constrained LLM client using llama-cpp-python with GBNF.

Called by: llm.packet_writer
Calls: config, training.versioning
Owns tables: none
Config keys: base_url, grammar_context_window, grammar_file, grammar_model_path, llm, model, model_file_path
Tests: tests/test_grammar_client.py
"""

import gc
import logging
from pathlib import Path

import requests

from src.config import load_config

logger = logging.getLogger(__name__)

_GRAMMAR = None
_MODEL = None
_MODEL_KEY: tuple[str, str] | None = None

# #166: minimum free VRAM (MB) required before loading grammar model
_MIN_FREE_VRAM_MB = 1500


def _import_llama_cpp():
    """Import llama_cpp lazily so the dependency remains optional."""
    try:
        from llama_cpp import Llama, LlamaGrammar
        return Llama, LlamaGrammar
    except ImportError:
        logger.warning("[GRAMMAR] llama_cpp not installed; grammar enforcement unavailable")
        return None, None


def _resolve_model_path(config: dict) -> Path | None:
    """Find the active GGUF path for llama.cpp."""
    llm_cfg = config.get("llm", {})

    explicit = llm_cfg.get("grammar_model_path") or llm_cfg.get("model_file_path")
    if explicit:
        path = Path(explicit)
        if path.exists():
            return path

    try:
        from src.training.versioning import get_active_model_version

        active = get_active_model_version()
        if active:
            model_file = active.get("model_file_path")
            if model_file:
                candidate = Path(model_file)
                if candidate.exists():
                    return candidate
    except Exception as exc:
        logger.debug("[GRAMMAR] Active model lookup failed: %s", exc)

    training_dir = Path("training_data")
    for candidate in sorted(training_dir.rglob("*.gguf"), reverse=True):
        return candidate

    logger.warning("[GRAMMAR] No GGUF model file found for grammar enforcement")
    return None


def _unload_ollama_if_running(config: dict) -> None:
    """Best-effort Ollama unload to free VRAM before llama.cpp starts."""
    llm_cfg = config.get("llm", {})
    model = llm_cfg.get("model")
    base_url = llm_cfg.get("base_url", "http://localhost:11434")
    if not model:
        return

    try:
        requests.post(
            f"{base_url}/api/generate",
            json={"model": model, "prompt": "", "keep_alive": 0, "stream": False},
            timeout=10,
        )
        logger.info("[GRAMMAR] Requested Ollama unload for %s", model)
    except Exception as exc:
        logger.debug("[GRAMMAR] Ollama unload skipped: %s", exc)


def _release_model() -> None:
    """Release previous model state and reclaim VRAM.

    #163: Prevents VRAM leak when model version changes by explicitly
    deleting the cached model, running gc, and clearing CUDA cache.
    """
    global _MODEL, _GRAMMAR, _MODEL_KEY
    if _MODEL is not None:
        logger.info("[GRAMMAR] Releasing previous model to free VRAM")
        del _MODEL
        _MODEL = None
    if _GRAMMAR is not None:
        del _GRAMMAR
        _GRAMMAR = None
    _MODEL_KEY = None
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            logger.debug("[GRAMMAR] CUDA cache cleared")
    except ImportError:
        pass


def _load_runtime() -> tuple[object | None, object | None]:
    """Load and cache the llama.cpp runtime and grammar file."""
    global _GRAMMAR, _MODEL, _MODEL_KEY

    config = load_config()
    llm_cfg = config.get("llm", {})
    grammar_file = Path(llm_cfg.get("grammar_file", "config/trade_commentary.gbnf"))
    model_path = _resolve_model_path(config)
    if model_path is None or not grammar_file.exists():
        if not grammar_file.exists():
            logger.warning("[GRAMMAR] Grammar file not found: %s", grammar_file)
        return None, None

    cache_key = (str(model_path.resolve()), str(grammar_file.resolve()))
    if _MODEL is not None and _GRAMMAR is not None and _MODEL_KEY == cache_key:
        return _MODEL, _GRAMMAR

    # #163: release previous model before loading new one to avoid VRAM leak
    if _MODEL is not None and _MODEL_KEY != cache_key:
        logger.info("[GRAMMAR] Model version changed — releasing old model")
        _release_model()

    Llama, LlamaGrammar = _import_llama_cpp()
    if Llama is None or LlamaGrammar is None:
        return None, None

    _unload_ollama_if_running(config)

    try:
        _GRAMMAR = LlamaGrammar.from_file(str(grammar_file))
        _MODEL = Llama(
            model_path=str(model_path),
            n_gpu_layers=-1,
            n_ctx=llm_cfg.get("grammar_context_window", 4096),
            verbose=False,
        )
        _MODEL_KEY = cache_key
        logger.info("[GRAMMAR] Loaded grammar runtime from %s", model_path)
        return _MODEL, _GRAMMAR
    except Exception as exc:
        logger.warning("[GRAMMAR] Failed to load grammar runtime: %s", exc)
        _GRAMMAR = None
        _MODEL = None
        _MODEL_KEY = None
        return None, None


def generate_with_grammar(
    prompt: str,
    system_prompt: str,
    max_tokens: int = 2048,
    temperature: float = 0.7,
) -> str | None:
    """Generate XML-constrained trade commentary, or None if unavailable."""
    model, grammar = _load_runtime()
    if model is None or grammar is None:
        return None

    try:
        result = model.create_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            grammar=grammar,
        )
        return result["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.warning("[GRAMMAR] Generation failed: %s", exc)
        return None
