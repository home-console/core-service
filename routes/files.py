"""
File transfer routes.
Handles file uploads, downloads, and transfer management.
"""
import os
import tempfile
import shutil
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import JSONResponse, StreamingResponse
import httpx

try:
    from ..utils.http_client import _http_json, _http_multipart_stream
except ImportError:
    from utils.http_client import _http_json, _http_multipart_stream

router = APIRouter()


@router.post("/files/upload")
async def upload_file_from_browser(
    client_id: str = Form(...),
    dest_path: str = Form(...),
    file: UploadFile = File(...),
) -> JSONResponse:
    """Upload file from browser to client via client_manager."""
    if not client_id or not dest_path:
        raise HTTPException(status_code=400, detail="client_id и dest_path обязательны")

    tmp_path = None
    try:
        original_name = file.filename
        # Save to temp file and stream it
        tmp_dir = os.getenv("UPLOAD_TMP_DIR", "/tmp")
        fd, tmp_path = tempfile.mkstemp(prefix="upload_", dir=tmp_dir)
        os.close(fd)
        with open(tmp_path, "wb") as out_f:
            await file.seek(0)
            shutil.copyfileobj(file.file, out_f)
        await file.close()
    except Exception as e:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"Не удалось прочитать файл: {e}")

    fields = {
        "client_id": client_id,
        "path": dest_path,
        "original_filename": original_name or "",
        "direction": "upload",
    }
    try:
        data = await _http_multipart_stream(
            "/api/files/upload/init",
            fields,
            "file",
            original_name or "upload.bin",
            tmp_path
        )
        return JSONResponse(data)
    except HTTPException as he:
        raise he
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass


@router.post("/files/upload/init")
async def upload_init_proxy(request: Request):
    """Proxy endpoint for upload initialization."""
    content_type = request.headers.get('content-type', '')
    
    # If multipart, reuse upload_file_from_browser logic
    if content_type.startswith('multipart/form-data'):
        form = await request.form()
        client_id = form.get('client_id')
        dest_path = form.get('path') or form.get('dest_path')
        upload_file = form.get('file')
        if not client_id or not dest_path or not upload_file:
            raise HTTPException(status_code=400, detail='client_id, path и file обязательны')
        return await upload_file_from_browser(client_id=client_id, dest_path=dest_path, file=upload_file)

    # Otherwise expect JSON
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid request body')
    
    try:
        data = await _http_json('POST', '/api/files/upload/init', body=body)
        return JSONResponse(data)
    except HTTPException as he:
        raise he


@router.get("/files/transfers/{transfer_id}/status")
async def transfer_status_proxy(transfer_id: str) -> JSONResponse:
    """Get transfer status."""
    data = await _http_json("GET", f"/api/files/transfers/{transfer_id}/status")
    return JSONResponse(data)


@router.post("/files/transfers/pause")
async def transfer_pause_proxy(payload: Dict[str, Any]) -> JSONResponse:
    """Pause transfer."""
    data = await _http_json("POST", "/api/files/transfers/pause", body=payload)
    return JSONResponse(data)


@router.post("/files/transfers/resume")
async def transfer_resume_proxy(payload: Dict[str, Any]) -> JSONResponse:
    """Resume transfer."""
    data = await _http_json("POST", "/api/files/transfers/resume", body=payload)
    return JSONResponse(data)


@router.post("/files/transfers/cancel")
async def transfer_cancel_proxy(payload: Dict[str, Any]) -> JSONResponse:
    """Cancel transfer."""
    data = await _http_json("POST", "/api/files/transfers/cancel", body=payload)
    return JSONResponse(data)


@router.post("/files/download")
async def initiate_download(client_id: str = Form(...), path: str = Form(...)) -> JSONResponse:
    """Initiate file download from client."""
    body = {"client_id": client_id, "path": path, "direction": "download"}
    data = await _http_json("POST", "/api/files/upload/init", body=body)
    return JSONResponse(data)


@router.get("/files/download/{transfer_id}")
async def proxy_download(transfer_id: str):
    """Proxy file download from client_manager."""
    base = os.getenv("CM_BASE_URL", "http://127.0.0.1:10000")
    base_url = base.rstrip('/')
    path = f"/api/files/transfers/{transfer_id}/download"
    full_url = f"{base_url}{path}"
    
    try:
        from ..utils.http_client import _get_http_client
    except ImportError:
        from utils.http_client import _get_http_client
    
    client = _get_http_client()
    
    try:
        async with client.stream('GET', full_url, timeout=30.0) as response:
            response.raise_for_status()
            
            async def stream():
                async for chunk in response.aiter_bytes():
                    yield chunk
            
            content_type = response.headers.get('Content-Type', 'application/octet-stream')
            return StreamingResponse(
                stream(),
                media_type=content_type,
                headers={}
            )
    except httpx.HTTPStatusError as e:
        error_text = e.response.text if e.response else "Download error"
        raise HTTPException(
            status_code=e.response.status_code if e.response else 500,
            detail=error_text
        )
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
        raise HTTPException(
            status_code=503,
            detail=f"Client manager unavailable: {str(e)}"
        )
