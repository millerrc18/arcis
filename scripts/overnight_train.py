"""Overnight training pipeline -- runs as subprocess for VRAM isolation.

When to run:
    Launched by the watch loop's evening phase (6:50 PM ET) as a subprocess.
    Can also be run manually for testing. Running as a subprocess ensures
    the training process gets its own VRAM allocation without competing
    with the Ollama inference server.

What it reads:
    - Training examples from the database
    - Model weights from the current active model version

What it writes:
    - Updated model weights (new version registered in model_versions table)
    - Training metrics to the database

Prerequisites:
    - CUDA-capable GPU with sufficient VRAM (RTX 3060 12GB minimum)
    - Ollama should be stopped before training to free VRAM (handled by VRAM handoff)
    - requirements-training.txt dependencies installed (PEFT, TRL, BitsAndBytes)
"""

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
    # Exit 0 if at least one training step completed; exit 1 otherwise.
    # The watch loop checks the exit code to decide whether to send
    # a success or failure Telegram notification.
    completed = sum(1 for r in results if r["status"] == "completed")
    sys.exit(0 if completed > 0 else 1)
