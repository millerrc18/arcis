"""Read-only config/Ollama post-reset verification (#95) — spec §Phase6.2 / MAJOR-3.

The L2 (config) and L3 (Ollama) resets are EMITTED instructions only (auto-editing
prod YAML risks cp1252 corruption — memory feedback_windows_utf8_encoding), so a
DB-only Phase-6 post-verify can report POST_VERIFY PASSED while the system still
serves the fine-tune or holds stale capital. `verify_post_reset_config` READS (never
edits) `config/settings.local.yaml` (utf-8) and the Ollama loaded tag, asserting:
  - llm.model            == base_tag (if base_tag is given)
  - live_trading.post_bootcamp == False
  - risk.starting_capital      == 100000

Returns a verdict dict (PASSED / FAILED with the specific failing assertions). Never
mutates config, never places Ollama pull/load commands.

Tests: tests/scripts/test_clean_slate_wipe.py (config-verify cases)
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_EXPECTED_STARTING_CAPITAL = 100000


def _read_yaml(config_path: Path) -> dict[str, Any]:
    """Read a YAML file as utf-8. Returns {} if absent/empty."""
    if not config_path.exists():
        return {}
    import yaml

    text = config_path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {}


def _ollama_loaded_models() -> list[str] | None:
    """Return the list of currently-loaded Ollama model names, or None if the
    Ollama CLI is unavailable / errored (best-effort; not a hard failure)."""
    try:
        result = subprocess.run(
            ["ollama", "ps"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        logger.warning("ollama ps unavailable: %s", exc)
        return None
    if result.returncode != 0:
        logger.warning("ollama ps returned %d: %s", result.returncode, result.stderr)
        return None
    # `ollama ps` prints a header row then one row per loaded model; the model
    # name is the first whitespace-delimited token of each non-header line.
    lines = [ln for ln in (result.stdout or "").splitlines() if ln.strip()]
    models: list[str] = []
    for ln in lines[1:]:  # skip header
        models.append(ln.split()[0])
    return models


def verify_post_reset_config(
    config_path: Path | str,
    *,
    base_tag: str | None = None,
    check_ollama: bool = True,
) -> dict[str, Any]:
    """Assert the post-reset config (and optionally Ollama) is clean-slate.

    Args:
        config_path: path to config/settings.local.yaml (read utf-8).
        base_tag:    expected base Ollama tag for llm.model. If None, the
                     llm.model assertion is skipped (only post_bootcamp +
                     starting_capital are checked).
        check_ollama: if True and base_tag is given, assert the base tag is
                     among the loaded Ollama models (best-effort; an
                     unavailable Ollama CLI is recorded, not a hard FAIL).

    Returns a verdict dict:
        {result: 'POST_VERIFY_CONFIG_PASSED'|'POST_VERIFY_CONFIG_FAILED',
         failures: [str, ...], config: {llm_model, post_bootcamp,
         starting_capital}, ollama_loaded: [...]|None}
    """
    cfg_path = Path(config_path)
    cfg = _read_yaml(cfg_path)
    failures: list[str] = []

    if not cfg_path.exists():
        failures.append(f"config file absent: {cfg_path}")

    llm_model = (cfg.get("llm") or {}).get("model")
    post_bootcamp = (cfg.get("live_trading") or {}).get("post_bootcamp")
    starting_capital = (cfg.get("risk") or {}).get("starting_capital")

    if base_tag is not None and llm_model != base_tag:
        failures.append(
            f"llm.model={llm_model!r} != base_tag {base_tag!r} (still serving fine-tune?)"
        )
    if post_bootcamp is not False:
        failures.append(
            f"live_trading.post_bootcamp={post_bootcamp!r} != False"
        )
    if starting_capital != _EXPECTED_STARTING_CAPITAL:
        failures.append(
            f"risk.starting_capital={starting_capital!r} != {_EXPECTED_STARTING_CAPITAL}"
        )

    ollama_loaded: list[str] | None = None
    if check_ollama and base_tag is not None:
        ollama_loaded = _ollama_loaded_models()
        if ollama_loaded is not None and base_tag not in ollama_loaded:
            failures.append(
                f"base tag {base_tag!r} not among loaded Ollama models {ollama_loaded}"
            )

    return {
        "result": "POST_VERIFY_CONFIG_FAILED" if failures else "POST_VERIFY_CONFIG_PASSED",
        "failures": failures,
        "config": {
            "llm_model": llm_model,
            "post_bootcamp": post_bootcamp,
            "starting_capital": starting_capital,
        },
        "ollama_loaded": ollama_loaded,
    }
