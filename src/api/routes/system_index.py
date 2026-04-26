"""Local mirror of the /api/system/index routes.

Called by: api.app
Calls: src.api.cloud_routes.system_index (shared router factory)
Owns tables: none (operator_view_state writes via cloud_routes.system_index)
Config keys: none
Tests: tests/api/test_route_parity.py

Endpoints:
    GET  /system/index                          - Full capability registry index
    POST /system/index/{entry_name}/mark-reviewed - Mark an entry as reviewed
"""

from fastapi import APIRouter

from src.api.cloud_routes.system_index import create_router as _create_cloud_router

_SENTINEL = object()


def _noop_auth():
    return True


router: APIRouter = _create_cloud_router(runtime=_SENTINEL, verify_auth=_noop_auth)
