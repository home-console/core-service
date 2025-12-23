"""
Enrollment routes (TOFU - Trust On First Use).
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

try:
    from ..utils.http_client import _http_json
    from ..utils.auth import get_admin_headers
except ImportError:
    from utils.http_client import _http_json
    from utils.auth import get_admin_headers

router = APIRouter()


@router.get("/enrollments/pending")
async def enrollments_pending() -> JSONResponse:
    """Get pending enrollment requests."""
    data = await _http_json("GET", "/api/enrollments/pending", headers=get_admin_headers())
    return JSONResponse(data)


@router.get("/admin/api/enrollments/pending")
async def enrollments_pending_compat() -> JSONResponse:
    """Compatibility endpoint."""
    return await enrollments_pending()


@router.post("/enrollments/{client_id}/approve")
async def enroll_approve(client_id: str) -> JSONResponse:
    """Approve client enrollment."""
    data = await _http_json("POST", f"/api/enrollments/{client_id}/approve", headers=get_admin_headers())
    return JSONResponse(data)


@router.post("/admin/api/enrollments/{client_id}/approve")
async def enroll_approve_compat(client_id: str) -> JSONResponse:
    """Compatibility endpoint."""
    return await enroll_approve(client_id)


@router.post("/enrollments/{client_id}/reject")
async def enroll_reject(client_id: str) -> JSONResponse:
    """Reject client enrollment."""
    data = await _http_json("POST", f"/api/enrollments/{client_id}/reject", headers=get_admin_headers())
    return JSONResponse(data)


@router.post("/admin/api/enrollments/{client_id}/reject")
async def enroll_reject_compat(client_id: str) -> JSONResponse:
    """Compatibility endpoint."""
    return await enroll_reject(client_id)
