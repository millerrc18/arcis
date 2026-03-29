"""Cloud council and activity routes for session review pages.

Called by: cloud_app.py
Calls: council_sessions, activity_log
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException


def create_router(runtime, verify_auth):
    """Build the cloud council router."""
    router = APIRouter()

    @router.get("/api/council/latest", dependencies=[Depends(verify_auth)])
    def council_latest():
        try:
            session = runtime.query_one(
                "SELECT * FROM council_sessions ORDER BY created_at DESC LIMIT 1"
            )
            if not session:
                return {"session": None}

            session = runtime.parse_json_fields(session, ["result_json"])
            votes = runtime.query(
                "SELECT * FROM council_votes WHERE session_id = %s ORDER BY round, agent_name",
                (session["session_id"],),
            )
            for vote in votes:
                runtime.parse_json_fields(vote, ["key_data_points", "risk_flags"])
            session["votes"] = votes
            return session
        except HTTPException:
            raise
        except Exception as exc:
            runtime.logger.error("Council latest error: %s", exc)
            return {"session": None, "error": str(exc)}

    @router.get("/api/council/history", dependencies=[Depends(verify_auth)])
    def council_history(days: int = 30):
        try:
            cutoff = (datetime.now(runtime.et) - timedelta(days=days)).isoformat()
            return runtime.query(
                "SELECT * FROM council_sessions WHERE created_at >= %s "
                "ORDER BY created_at DESC",
                (cutoff,),
            )
        except HTTPException:
            raise
        except Exception as exc:
            runtime.logger.error("Council history error: %s", exc)
            return []

    @router.get("/api/council/session/{session_id}", dependencies=[Depends(verify_auth)])
    def council_session_detail(session_id: str):
        try:
            session = runtime.query_one(
                "SELECT * FROM council_sessions WHERE session_id = %s",
                (session_id,),
            )
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")

            session = runtime.parse_json_fields(session, ["result_json"])
            votes = runtime.query(
                "SELECT * FROM council_votes WHERE session_id = %s ORDER BY round, agent_name",
                (session_id,),
            )
            for vote in votes:
                runtime.parse_json_fields(vote, ["key_data_points", "risk_flags"])
            return {"session": session, "votes": votes}
        except HTTPException:
            raise
        except Exception as exc:
            runtime.logger.error("Council session detail error: %s", exc)
            return {"session": None, "votes": [], "error": str(exc)}

    @router.get("/api/activity/feed", dependencies=[Depends(verify_auth)])
    def activity_feed(limit: int = 50, event_type: str | None = None):
        try:
            if event_type:
                return runtime.query(
                    "SELECT * FROM activity_log WHERE event_type = %s "
                    "ORDER BY created_at DESC LIMIT %s",
                    (event_type, limit),
                )
            return runtime.query(
                "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
        except HTTPException:
            raise
        except Exception as exc:
            runtime.logger.error("Activity feed error: %s", exc)
            return []

    @router.post("/api/council/strategic", dependencies=[Depends(verify_auth)])
    def council_strategic():
        return {
            "error": "cloud_mode",
            "message": "Strategic council questions must be run from the local dashboard/API.",
        }

    return router
