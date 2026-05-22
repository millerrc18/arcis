"""Absolute STOP-flag path and helpers for overnight training halt.

Called by: training.training_control (T4), scheduler.overnight (T11)
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_training_stop.py
"""

import os

from src.config import DB_PATH

STOP_FLAG: str = os.path.join(os.path.dirname(DB_PATH), "STOP_OVERNIGHT")


def set_stop() -> None:
    open(STOP_FLAG, "w").close()


def clear_stop() -> None:
    try:
        os.remove(STOP_FLAG)
    except FileNotFoundError:
        pass


def is_stop_requested() -> bool:
    return os.path.exists(STOP_FLAG)
