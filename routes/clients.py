"""
Client management routes.
Handles client connections, command execution, and installations.
"""
from typing import Dict, Any
from datetime import datetime
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Form
from fastapi.responses import JSONResponse
from sqlalchemy import select

from ..core.database import get_session
from ..utils.http_client import _http_json
from ..utils.auth import get_admin_headers, generate_jwt_token

import os
import uuid

router = APIRouter()


@router.get("/clients")
async def clients_list() -> JSONResponse:
    """Get list of connected clients."""
    data = await _http_json("GET", "/api/clients")
    
    # Update snapshot in DB
    async with get_session() as db:
        for c in data:
            result = await db.execute(select(Client).where(Client.id == c.get("id")))
            obj = result.scalar_one_or_none()
            
            if obj is None:
                obj = Client(id=c.get("id"))
                db.add(obj)
            
            obj.hostname = c.get("hostname")
            obj.ip = c.get("ip")
            obj.port = c.get("port")
            obj.status = c.get("status")
            
            def _parse(dt):
                try:
                    return datetime.fromisoformat(dt) if dt else None
                except Exception:
                    return None
            
            obj.connected_at = _parse(c.get("connected_at"))
            obj.last_heartbeat = _parse(c.get("last_heartbeat"))
            await db.merge(obj)
    
    return JSONResponse(data)


@router.get("/admin/api/clients")
async def clients_list_compat() -> JSONResponse:
    """Compatibility endpoint."""
    return await clients_list()


@router.post("/commands/{client_id}")
async def command_exec(client_id: str, payload: Dict[str, Any]) -> JSONResponse:
    """Execute command on client."""
    # Save command as queued
    command_id: str | None = None
    if payload and isinstance(payload, dict):
        command_text = payload.get("command") or (str(payload.get("name")) + " " + str(payload.get("params")))
    else:
        command_text = None
    
    if command_text:
        async with get_session() as db:
            cid = f"cmd_{int(datetime.utcnow().timestamp())}"
            log = CommandLog(id=cid, client_id=client_id, command=command_text, status="queued")
            await db.merge(log)
            command_id = cid

    data = await _http_json("POST", f"/api/commands/{client_id}", body=payload)

    # Update record with result
    if command_id and isinstance(data, dict):
        async with get_session() as db:
            result = await db.execute(select(CommandLog).where(CommandLog.id == command_id))
            log = result.scalar_one_or_none()
            if log:
                success = data.get("success")
                log.status = "success" if success else "failed"
                log.stdout = data.get("result")
                log.stderr = data.get("error")
                log.exit_code = data.get("exit_code")
                log.finished_at = datetime.utcnow()
                await db.merge(log)

    return JSONResponse(data)


@router.post("/admin/api/commands/{client_id}")
async def command_exec_compat(client_id: str, payload: Dict[str, Any]) -> JSONResponse:
    """Compatibility endpoint."""
    return await command_exec(client_id, payload)


@router.post("/commands/{client_id}/cancel")
async def command_cancel(client_id: str, command_id: str) -> JSONResponse:
    """Cancel running command."""
    path = f"/api/commands/{client_id}/cancel?" + urlencode({"command_id": command_id})
    data = await _http_json("POST", path)
    return JSONResponse(data)


@router.post("/admin/api/commands/{client_id}/cancel")
async def command_cancel_compat(client_id: str, command_id: str) -> JSONResponse:
    """Compatibility endpoint."""
    return await command_cancel(client_id, command_id)


@router.get("/commands/history")
async def commands_history() -> JSONResponse:
    """Get command execution history."""
    data = await _http_json("GET", "/api/commands/history")
    return JSONResponse(data)


@router.get("/commands/{command_id}")
async def command_result(command_id: str) -> JSONResponse:
    """Get command execution result."""
    data = await _http_json("GET", f"/api/commands/{command_id}")
    return JSONResponse(data)


@router.post("/clients/{client_id}/install")
async def client_install(client_id: str, payload: Dict[str, Any]) -> JSONResponse:
    """
    Trigger remote installation on agent.
    
    Expected payload:
      - install_token: Required by agent
      - dry_run: Optional boolean
      - socket, sessions_dir, token_file: Optional
    """
    # Build message for client_manager
    msg = {
        "client_id": client_id,
        "message": {
            "type": "admin.install_service",
            "data": {
                "install_token": payload.get("install_token"),
                "dry_run": payload.get("dry_run", True),
                "socket": payload.get("socket"),
                "sessions_dir": payload.get("sessions_dir"),
                "token_file": payload.get("token_file"),
            },
        },
    }

    try:
        headers = get_admin_headers()
        if not headers:
            raise HTTPException(status_code=403, detail="Server ADMIN_TOKEN or ADMIN_JWT_SECRET not configured")
        
        data = await _http_json('POST', '/api/admin/send_message', body=msg, headers=headers)
    except HTTPException as he:
        raise he

    # Audit log
    try:
        async with get_session() as db:
            cid = f"install_{uuid.uuid4().hex}"
            log = CommandLog(id=cid, client_id=client_id, command="install_pty_manager", status="sent")
            await db.merge(log)
    except Exception:
        pass

    return JSONResponse({"ok": True, "forwarded": data})
