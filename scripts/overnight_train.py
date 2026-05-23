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
    - training/requirements.txt dependencies installed (PEFT, TRL, BitsAndBytes)
      (relocated from requirements-training.txt at repo root in v0.36.55/#101
      so GitHub auto dep-submission stops scanning the unsloth git+URL)
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

# Fix: src.scheduler.overnight doesn't exist. The actual training entry points are:
#   - src.training.data_collector.collect_training_examples_from_closed_trades
#   - src.training.trainer.run_fine_tune
from src.training.data_collector import collect_training_examples_from_closed_trades
from src.training.trainer import run_fine_tune

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    results = []

    # Step 1: Collect training examples from today's closed trades
    try:
        count = collect_training_examples_from_closed_trades()
        results.append({"step": "collect", "status": "completed", "examples": count})
        logger.info("[OVERNIGHT] Collected %d training examples", count)
    except Exception as e:
        results.append({"step": "collect", "status": "failed", "error": str(e)})
        logger.error("[OVERNIGHT] Training collection failed: %s", e)

    # Step 2: Run fine-tuning if we have enough examples
    try:
        result = run_fine_tune()
        if result:
            results.append({"step": "fine_tune", "status": "completed", "model": result})
            logger.info("[OVERNIGHT] Fine-tuning completed: %s", result)
        else:
            results.append({"step": "fine_tune", "status": "skipped", "reason": "insufficient data"})
            logger.info("[OVERNIGHT] Fine-tuning skipped — insufficient data")
    except Exception as e:
        results.append({"step": "fine_tune", "status": "failed", "error": str(e)})
        logger.error("[OVERNIGHT] Fine-tuning failed: %s", e)

    # Exit 0 if at least one step completed; exit 1 otherwise.
    completed = sum(1 for r in results if r["status"] == "completed")
    sys.exit(0 if completed > 0 else 1)
