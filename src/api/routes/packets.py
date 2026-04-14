"""Packets API routes.

Called by: api.app
Calls: journal.store
Owns tables: none
Config keys: none
Tests: tests/test_local_api_routes.py

Endpoints:
    GET /packets                     - List packets (filterable by days/ticker/score)
    GET /packets/{recommendation_id} - Single packet detail

A "packet" is a recommendation object -- the system's buy thesis for a ticker.
The name comes from the original design where each recommendation was a
self-contained research packet with thesis, price targets, and risk analysis.
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
        recs = [r for r in recs if float(r.get("priority_score") or 0) >= min_score]

    return recs


@router.get("/packets/{recommendation_id}")
def get_packet(recommendation_id: str):
    rec = get_recommendation_by_id(recommendation_id)
    if rec:
        return rec
    return {"error": "Not found"}
