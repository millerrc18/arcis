"""Regression lock: run_evening_handoff and run_morning_handoff must NOT exist
in src.scheduler.overnight after T11 deletion.

Also asserts that vram_manager/VRAMManager, vram_handoff metric names, and the
relative data/STOP_OVERNIGHT path are absent from the module source.
"""

import importlib
import inspect
import src.scheduler.overnight as overnight


def test_run_evening_handoff_absent():
    assert not hasattr(overnight, "run_evening_handoff"), (
        "run_evening_handoff was not deleted from src.scheduler.overnight"
    )


def test_run_morning_handoff_absent():
    assert not hasattr(overnight, "run_morning_handoff"), (
        "run_morning_handoff was not deleted from src.scheduler.overnight"
    )


def test_no_vram_manager_reference_in_source():
    source = inspect.getsource(overnight)
    assert "vram_manager" not in source, (
        "src.scheduler.overnight still references 'vram_manager'"
    )
    assert "VRAMManager" not in source, (
        "src.scheduler.overnight still references 'VRAMManager'"
    )


def test_no_vram_handoff_metric_in_source():
    source = inspect.getsource(overnight)
    assert "vram_handoff_training_ok" not in source, (
        "src.scheduler.overnight still contains 'vram_handoff_training_ok' metric write"
    )
    assert "vram_handoff_inference_ok" not in source, (
        "src.scheduler.overnight still contains 'vram_handoff_inference_ok' metric write"
    )


def test_no_relative_stop_overnight_path_in_source():
    source = inspect.getsource(overnight)
    assert 'Path("data/STOP_OVERNIGHT")' not in source, (
        "src.scheduler.overnight still contains relative data/STOP_OVERNIGHT Path"
    )


def test_overnight_module_imports_cleanly():
    """Re-import to confirm the module parses with no ImportError from removed imports."""
    importlib.reload(overnight)
