"""Overnight training pipeline -- runs as subprocess for VRAM isolation."""

import logging
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from src.scheduler.overnight import OvernightPipeline

if __name__ == "__main__":
    pipeline = OvernightPipeline()
    results = pipeline.run()
    completed = sum(1 for r in results if r["status"] == "completed")
    sys.exit(0 if completed > 0 else 1)
