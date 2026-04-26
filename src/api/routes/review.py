"""Review API routes.

Called by: api.app
Calls: services.review_service
Owns tables: none
Config keys: none
Tests: tests/test_local_api_routes.py

Endpoints:
    GET  /review/pending                   - Trades awaiting human review
    GET  /review/scorecard?weeks=1         - Win/loss scorecard
    GET  /review/postmortems               - List of trade postmortems
    GET  /review/postmortem/{id}           - Single postmortem detail
    GET  /review/{recommendation_id}       - Single review detail
    POST /review/{recommendation_id}       - Submit human review (approve/grade/notes)
    POST /review/mark-executed/{ticker}    - Mark a ticker as manually executed

The review system is how the operator grades the system's recommendations.
ryan_approved, user_grade, and repeatable_setup fields feed back into the
training pipeline -- high-quality reviews become training examples that
teach the model what good setups look like.
"""
from fastapi import APIRouter, Depends
from src.api.local_auth import verify_local_token
from src.services.review_service import (
    get_pending_reviews, get_recommendation, submit_review,
    mark_executed, get_scorecard, get_postmortems, get_postmortem_detail,
)

router = APIRouter(tags=["review"])


@router.get("/review/pending")
def pending_reviews():
    return get_pending_reviews()


@router.get("/review/scorecard")
def scorecard(weeks: int = 1):
    return {"scorecard": get_scorecard(weeks=weeks)}


@router.get("/review/postmortems")
def postmortems(limit: int = 10, ticker: str | None = None):
    return get_postmortems(limit=limit, ticker=ticker)


@router.get("/review/postmortem/{recommendation_id}")
def postmortem_detail(recommendation_id: str):
    result = get_postmortem_detail(recommendation_id)
    if result:
        return result
    return {"error": "Not found"}


@router.get("/review/{recommendation_id}")
def review_detail(recommendation_id: str):
    result = get_recommendation(recommendation_id)
    if result:
        return result
    return {"error": "Not found"}


@router.post("/review/{recommendation_id}", dependencies=[Depends(verify_local_token)])
def submit_review_endpoint(recommendation_id: str, data: dict):
    review_data = {}
    if "ryan_approved" in data:
        review_data["ryan_approved"] = 1 if data["ryan_approved"] else 0
    if "ryan_executed" in data:
        review_data["ryan_executed"] = 1 if data["ryan_executed"] else 0
    if "user_grade" in data:
        review_data["user_grade"] = data["user_grade"]
    if "ryan_notes" in data:
        review_data["ryan_notes"] = data["ryan_notes"]
    if "repeatable_setup" in data:
        review_data["repeatable_setup"] = 1 if data["repeatable_setup"] else 0

    success = submit_review(recommendation_id, review_data)
    return {"success": success}


@router.post("/review/mark-executed/{ticker}", dependencies=[Depends(verify_local_token)])
def mark_executed_endpoint(ticker: str):
    success = mark_executed(ticker)
    return {"success": success}
