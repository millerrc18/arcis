"""Thin CLI shim — defers to src.shadow_trading.bracket_attach.

The real implementation lives at ``src/shadow_trading/bracket_attach.py``.
This script is kept for muscle-memory; same as running:
    python -m src.shadow_trading.bracket_attach [--dry-run]

Usage:
    python scripts/reattach_brackets.py            # submit
    python scripts/reattach_brackets.py --dry-run  # preview only
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("ARCIS_PG_CUTOVER_ENABLED", "1")

from src.shadow_trading.bracket_attach import _main

if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
