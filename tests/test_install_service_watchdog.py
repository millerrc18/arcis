"""Static-review tests for scripts/install_service.ps1 watchdog block.

These tests NEVER execute the PowerShell script. They read it as text and
assert that the required NSSM directives for ArcisOllamaWatchdog are present
(or absent, in the DependOnService case).

Test IDs:
  - test_installs_watchdog_with_correct_module_path
  - test_watchdog_app_environment_extra_has_all_three_vars
  - test_watchdog_app_exit_restart_and_app_throttle_present
  - test_watchdog_has_no_depend_on_service
"""

import pathlib

import pytest

_SCRIPT = pathlib.Path(__file__).parent.parent / "scripts" / "install_service.ps1"


@pytest.fixture(scope="module")
def script_text() -> str:
    return _SCRIPT.read_text(encoding="utf-8")


def test_installs_watchdog_with_correct_module_path(script_text: str) -> None:
    """install_service.ps1 must install ArcisOllamaWatchdog using the module
    path src.scheduler.ollama_watchdog (Wave-1 module confirmed at
    src/scheduler/ollama_watchdog.py).
    """
    assert "ArcisOllamaWatchdog" in script_text, (
        "install_service.ps1 must contain an install block for ArcisOllamaWatchdog"
    )
    assert "src.scheduler.ollama_watchdog" in script_text, (
        "The watchdog install must reference module path src.scheduler.ollama_watchdog"
    )


def test_watchdog_app_environment_extra_has_all_three_vars(script_text: str) -> None:
    """AppEnvironmentExtra for ArcisOllamaWatchdog must set all three required
    env vars: OLLAMA_MODELS, CUDA_VISIBLE_DEVICES=1, CUDA_DEVICE_ORDER=PCI_BUS_ID.
    """
    assert "OLLAMA_MODELS" in script_text, (
        "AppEnvironmentExtra must include OLLAMA_MODELS"
    )
    assert "CUDA_VISIBLE_DEVICES=1" in script_text, (
        "AppEnvironmentExtra must include CUDA_VISIBLE_DEVICES=1"
    )
    assert "CUDA_DEVICE_ORDER=PCI_BUS_ID" in script_text, (
        "AppEnvironmentExtra must include CUDA_DEVICE_ORDER=PCI_BUS_ID"
    )


def test_watchdog_app_exit_restart_and_app_throttle_present(script_text: str) -> None:
    """The watchdog install block must set both AppExit Default Restart AND
    AppThrottle so that recurring crashes escalate/surface rather than silently
    exhausting throttle (MAJOR-2 escalation requirement).
    """
    assert "AppExit" in script_text, (
        "install_service.ps1 must set AppExit for ArcisOllamaWatchdog"
    )
    # "Restart" must appear alongside AppExit
    assert "Restart" in script_text, (
        "AppExit must use Restart policy for ArcisOllamaWatchdog"
    )
    assert "AppThrottle" in script_text, (
        "install_service.ps1 must set AppThrottle for ArcisOllamaWatchdog"
    )


def test_watchdog_has_no_depend_on_service(script_text: str) -> None:
    """DependOnService must NOT appear anywhere in the watchdog install block.

    An SCM DependOnService wedge caused a 13-minute loop-down on 2026-05-22.
    Start ordering is handled at install time, not via SCM dependency.
    The existing ArcisWatchLoop block also does not use DependOnService, so
    a flat 'not in script_text' check is valid for the entire script.
    """
    assert "DependOnService" not in script_text, (
        "DependOnService must NOT appear in install_service.ps1 — "
        "SCM dependency wedge caused a 13-minute loop-down (2026-05-22)"
    )
