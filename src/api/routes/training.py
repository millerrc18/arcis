"""Training API routes.

Called by: api.app
Calls: services.training_service
Owns tables: none
Config keys: none
Tests: tests/test_local_api_routes.py
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
