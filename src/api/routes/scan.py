"""Scan API routes.

Called by: api.app
Calls: config, services.recap_service, services.scan_service, services.watchlist_service
Owns tables: none
Config keys: none
Tests: tests/test_local_api_routes.py
"""
from fastapi import APIRouter
from src.config import load_config
from src.services.scan_service import run_scan
from src.services.watchlist_service import generate_morning_watchlist
from src.services.recap_service import generate_eod_recap

router = APIRouter(tags=["scan"])

_latest_scan = None


@router.post("/scan")
def trigger_scan(dry_run: bool = False, email: bool = False):
    global _latest_scan
    config = load_config()
    result = run_scan(config, dry_run=dry_run, send_email_flag=email)
    _latest_scan = result
    return result


@router.get("/scan/latest")
def get_latest_scan():
    if _latest_scan is None:
        return {"message": "No scan has been run yet"}
    return _latest_scan


@router.post("/morning-watchlist")
def morning_watchlist(email: bool = False):
    config = load_config()
    return generate_morning_watchlist(config, send_email_flag=email)


@router.post("/eod-recap")
def eod_recap(email: bool = False):
    config = load_config()
    return generate_eod_recap(config, send_email_flag=email)
