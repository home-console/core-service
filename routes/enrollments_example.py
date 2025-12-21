"""
Example: How to extract routes from admin_app.py

This is a template showing how enrollment routes should be extracted.
Use this as a reference when extracting other route groups.
"""
import asyncio
from typing import Dict, Any
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

# Import utilities instead of duplicating code
try:
    from ..utils.http_client import _http_json
    from ..utils.auth import get_admin_headers
except ImportError:
    from utils.http_client import _http_json
    from utils.auth import get_admin_headers


# Create router with prefix and tags
router = APIRouter(
    prefix="/enrollments",
    tags=["enrollments"],
)


@router.get("/pending")
async def get_pending_enrollments() -> JSONResponse:
    """
    Get list of pending enrollment requests (TOFU).
    Requires ADMIN_TOKEN authentication.
    """
    data = await asyncio.to_thread(
        _http_json,
        "GET",
        "/api/enrollments/pending",
        headers=get_admin_headers()
    )
    return JSONResponse(data)


@router.post("/{client_id}/approve")
async def approve_enrollment(client_id: str) -> JSONResponse:
    """
    Approve a client enrollment request.
    Requires ADMIN_TOKEN authentication.
    """
    data = await asyncio.to_thread(
        _http_json,
        "POST",
        f"/api/enrollments/{client_id}/approve",
        headers=get_admin_headers()
    )
    return JSONResponse(data)


@router.post("/{client_id}/reject")
async def reject_enrollment(client_id: str) -> JSONResponse:
    """
    Reject a client enrollment request.
    Requires ADMIN_TOKEN authentication.
    """
    data = await asyncio.to_thread(
        _http_json,
        "POST",
        f"/api/enrollments/{client_id}/reject",
        headers=get_admin_headers()
    )
    return JSONResponse(data)


# ============= How to use this router =============
# In app.py or create_admin_app():
#
#   from .routes import enrollments_example
#   app.include_router(enrollments_example.router, prefix="/api")
#
# This will mount all routes under /api/enrollments/*
