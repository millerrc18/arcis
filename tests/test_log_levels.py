"""Assert log levels for routine events match operator expectations (#629).

Each call site listed here was previously logged at WARNING despite
being a routine, recoverable event that pollutes the operator's
WARNING+ stream. Demoting to DEBUG eliminates the noise while
preserving the diagnostic info for verbose troubleshooting.

If a future commit re-elevates one of these to WARNING/ERROR, this
test fails immediately so the change is conscious.
"""
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"


@pytest.mark.parametrize("file_rel,line_marker,expected_level", [
    # alpaca_adapter.py — [CANCEL] failures are routine (broker often
    # rejects cancels because order already filled/cancelled by bracket OCO)
    ("shadow_trading/alpaca_adapter.py", "[CANCEL] Could not cancel order", "debug"),
    ("shadow_trading/alpaca_adapter.py", "[CANCEL] Failed to cancel order", "debug"),
    ("shadow_trading/alpaca_adapter.py", "[CANCEL] Could not cancel all orders", "debug"),
    # 4th site discovered during PR-5 implementation — same shape, same fix.
    ("shadow_trading/alpaca_adapter.py", "[CANCEL] Could not list orders", "debug"),
])
def test_log_call_uses_expected_level(file_rel, line_marker, expected_level):
    """Verify the source line containing line_marker uses logger.<expected_level>."""
    src = (SRC_ROOT / file_rel).read_text()
    matches = []
    for i, line in enumerate(src.splitlines(), 1):
        if line_marker in line:
            # Look at this line and previous 1 (the logger call may wrap)
            window = "\n".join(src.splitlines()[max(0, i - 2):i])
            matches.append((i, window))
    assert matches, f"line_marker {line_marker!r} not found in {file_rel}"
    for line_no, window in matches:
        assert f"logger.{expected_level}(" in window, (
            f"{file_rel}:{line_no} expected logger.{expected_level} but got:\n{window}"
        )
