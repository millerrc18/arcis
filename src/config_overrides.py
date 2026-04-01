"""Backwards-compatibility shim for config overrides.

Called by: commands.executor, scheduler.watch, api.cloud_routes.core
Calls: src.config.overrides
Owns tables: none
Config keys: none
Tests: tests/test_command_queue.py

Real module is src.config.overrides. All imports forwarded so
existing code continues to work.
"""

from src.config.overrides import (  # noqa: F401
    BLOCKED_PREFIXES,
    WHITELISTED_KEYS,
    apply_override,
    clear_all_overrides,
    get_effective_config,
    get_overrides,
    get_settings_with_sources,
)
