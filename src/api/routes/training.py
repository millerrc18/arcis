"""Training API routes.

Called by: api.app
Calls: services.training_service
Owns tables: none
Config keys: none
Tests: tests/test_local_api_routes.py

Endpoints:
    GET  /training/status    - Active model, dataset counts, training readiness
    GET  /training/versions  - All model version history
    GET  /training/report    - Training quality report
    POST /training/bootstrap - Generate synthetic training examples
    POST /training/train     - Trigger fine-tuning (QLoRA on RTX 3060)
    POST /training/rollback  - Revert to previous model version

Training runs locally on the RTX 3060 via the VRAM handoff system
(Ollama unloads -> PyTorch fine-tunes -> Ollama reloads).
"""
from fastapi import APIRouter
from src.services.training_service import (
    get_training_status, get_training_history, get_training_report,
    run_bootstrap, run_fine_tune_service, rollback_model_service,
)

router = APIRouter(tags=["training"])


@router.get("/training/status")
def training_status():
    return get_training_status()


@router.get("/training/versions")
def training_versions():
    return get_training_history()


@router.get("/training/report")
def training_report():
    return {"report": get_training_report()}


@router.post("/training/bootstrap")
def bootstrap(count: int = 500):
    return run_bootstrap(count=count)


@router.post("/training/train")
def train():
    result = run_fine_tune_service()
    if result:
        return result
    return {"error": "Training failed"}


@router.post("/training/rollback")
def rollback():
    result = rollback_model_service()
    if result:
        return result
    return {"error": "No previous version to rollback to"}


@router.get("/model-performance")
def model_performance():
    """Per-model-version live performance metrics with equity curves and comparisons."""
    from src.evaluation.model_monitor import get_model_performance
    return get_model_performance()
