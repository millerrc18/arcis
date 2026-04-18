"""State query: bootcamp mode flag + phase.

Reads from the YAML config rather than the database because bootcamp is
a deployment-level decision, not a runtime-mutable state.
"""
from __future__ import annotations

from datetime import date

from src.platform.capability_registry import register_state


def _bootcamp_state_raw() -> dict:
    """Load bootcamp section from current config."""
    try:
        from src.config import load_config  # type: ignore[attr-defined]
        cfg = load_config()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"config unavailable: {exc}"}
    bc = (cfg or {}).get("bootcamp", {}) or {}
    return {
        "value": {
            "enabled": bool(bc.get("enabled", False)),
            "phase": int(bc.get("phase", 0)) if bc.get("enabled") else None,
            "qualification_threshold": int(bc.get("qualification_threshold", 0)),
            "email_mode": bc.get("email_mode", "digest"),
        },
    }


@register_state(
    name="bootcamp_mode",
    description=(
        "Whether bootcamp mode is active, its phase, and related "
        "qualification/email thresholds. Bootcamp relaxes training "
        "thresholds during the early-sample period."
    ),
    category="training",
    version="1.0",
    maintainer="operator",
    introduced_in="v0.15.0",
    last_reviewed_date=date(2026, 4, 18),
    refresh_hint="deploy-time",
)
def bootcamp_mode() -> dict:
    return _bootcamp_state_raw()
