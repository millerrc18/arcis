"""Packets API routes.

Called by: api.app
Calls: journal.store
Owns tables: none
Config keys: none
Tests: tests/test_local_api_routes.py
"""
from fastapi import APIRouter
from src.journal.store import get_recommendations_in_period, get_recommendation_by_id

router = APIRouter(tags=["packets"])


@router.get("/packets")
def list_packets(days: int = 7, ticker: str | None = None, min_score: float | None = None):
    recs = get_recommendations_in_period(days=days)

    if ticker:
        recs = [r for r in recs if r.get("ticker", "").upper() == ticker.upper()]

    if min_score is not None:
        recs = [r for r in recs if (r.get("priority_score") or 0) >= min_score]

    return recs


@router.get("/packets/{recommendation_id}")
def get_packet(recommendation_id: str):
    rec = get_recommendation_by_id(recommendation_id)
    if rec:
        return rec
    return {"error": "Not found"}
