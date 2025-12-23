"""
Client Manager Plugin - управление клиентами, файлами и регистрациями.
Объединяет функциональность управления агентами, файловыми операциями и TOFU enrollments.
"""
from typing import Dict, Any
from datetime import datetime
from urllib.parse import urlencode
import os
import uuid
import tempfile
import shutil

from fastapi import APIRouter, HTTPException, Form, UploadFile, File, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
import httpx

from home_console_sdk.plugin import InternalPluginBase

# Импортируем модели плагина
from .models import Client, CommandLog, Enrollment, TerminalAudit

# Импортируем утилиты из core
from ...utils.http_client import _http_json, _http_multipart_stream, _get_http_client
from ...utils.auth import get_admin_headers
from ...db import get_session


# Try import embed helper (for embedded mode)
try:
    from . import embed as embed_helper
except Exception:
    try:
        from embed import embed as embed_helper
    except Exception:
        embed_helper = None


class ClientManagerPlugin(InternalPluginBase):
    """Плагин управления клиентами, файлами и регистрациями."""
    
    id = "client_manager"
    name = "Client Manager"
    version = "1.0.0"
    description = "Manages clients, file transfers, and enrollments"
    
    # Поддерживаемые режимы
    SUPPORTED_MODES = ["in_process", "microservice"]
    
    async def on_load(self):
        """Инициализация плагина."""
        self.router = APIRouter()
        self._embedded_proc = None
        self._current_mode = "microservice"  # default

        # Получаем режим: сначала из env, потом из БД
        cm_mode = os.getenv("CM_MODE", "").lower()
        
        # Если не задан в env, пробуем прочитать из БД
        if not cm_mode:
            try:
                from sqlalchemy import select
                async with get_session() as db:
                    from ...models import Plugin
                    result = await db.execute(select(Plugin).where(Plugin.id == self.id))
                    plugin_record = result.scalar_one_or_none()
                    if plugin_record and plugin_record.runtime_mode:
                        if plugin_record.runtime_mode == "in_process":
                            cm_mode = "embedded"
                        else:
                            cm_mode = "external"
                        self.logger.info(f"📋 Loaded runtime_mode from DB: {plugin_record.runtime_mode}")
            except Exception as e:
                self.logger.debug(f"Could not read mode from DB: {e}")
        
        # Fallback на external
        if not cm_mode:
            cm_mode = "external"
        
        self.logger.info(f"🔧 Client Manager starting in mode: {cm_mode}")
        
        if cm_mode == "embedded" and embed_helper is not None:
            self._current_mode = "in_process"
            try:
                # Pass through environment (allow overriding CM_BASE_URL etc.)
                env = {}
                base = os.getenv("CM_BASE_URL")
                if not base:
                    # default internal URL
                    env["CM_BASE_URL"] = "http://127.0.0.1:10000"
                # Start embedded process
                proc = embed_helper.start_embedded(env=env)
                self._embedded_proc = proc
                self.logger.info("🔌 Started embedded client-manager-service (pid=%s)", getattr(proc, 'pid', None))
            except FileNotFoundError as e:
                self.logger.error("Failed to start embedded client-manager-service: %s", e)
                self.logger.warning("Falling back to external (microservice) mode for client_manager")
                self._current_mode = "microservice"
                cm_mode = "external"
            except Exception as e:
                self.logger.error("Failed to start embedded client-manager-service: %s", e)
                self.logger.warning("Falling back to external (microservice) mode for client_manager")
                self._current_mode = "microservice"
                cm_mode = "external"
        else:
            self._current_mode = "microservice"
            self.logger.info("🌐 Using external client-manager-service at %s", os.getenv("CM_BASE_URL", "http://client_manager:10000"))
        
        # ============= Client Routes =============
        self.router.add_api_route("/clients", self.clients_list, methods=["GET"])
        self.router.add_api_route("/admin/api/clients", self.clients_list_compat, methods=["GET"])
        self.router.add_api_route("/commands/{client_id}", self.command_exec, methods=["POST"])
        self.router.add_api_route("/admin/api/commands/{client_id}", self.command_exec_compat, methods=["POST"])
        self.router.add_api_route("/commands/{client_id}/cancel", self.command_cancel, methods=["POST"])
        self.router.add_api_route("/admin/api/commands/{client_id}/cancel", self.command_cancel_compat, methods=["POST"])
        self.router.add_api_route("/commands/history", self.commands_history, methods=["GET"])
        self.router.add_api_route("/commands/{command_id}", self.command_result, methods=["GET"])
        self.router.add_api_route("/clients/{client_id}/install", self.client_install, methods=["POST"])
        
        # ============= File Routes =============
        self.router.add_api_route("/files/upload", self.upload_file_from_browser, methods=["POST"])
        self.router.add_api_route("/files/upload/init", self.upload_init_proxy, methods=["POST"])
        self.router.add_api_route("/files/transfers/{transfer_id}/status", self.transfer_status_proxy, methods=["GET"])
        self.router.add_api_route("/files/transfers/pause", self.transfer_pause_proxy, methods=["POST"])
        self.router.add_api_route("/files/transfers/resume", self.transfer_resume_proxy, methods=["POST"])
        self.router.add_api_route("/files/transfers/cancel", self.transfer_cancel_proxy, methods=["POST"])
        self.router.add_api_route("/files/download", self.initiate_download, methods=["POST"])
        self.router.add_api_route("/files/download/{transfer_id}", self.proxy_download, methods=["GET"])
        
        # ============= Enrollment Routes =============
        self.router.add_api_route("/enrollments/pending", self.enrollments_pending, methods=["GET"])
        self.router.add_api_route("/admin/api/enrollments/pending", self.enrollments_pending_compat, methods=["GET"])
        self.router.add_api_route("/enrollments/{client_id}/approve", self.enroll_approve, methods=["POST"])
        self.router.add_api_route("/admin/api/enrollments/{client_id}/approve", self.enroll_approve_compat, methods=["POST"])
        self.router.add_api_route("/enrollments/{client_id}/reject", self.enroll_reject, methods=["POST"])
        self.router.add_api_route("/admin/api/enrollments/{client_id}/reject", self.enroll_reject_compat, methods=["POST"])
        
        # ============= Terminal Audit Route =============
        self.router.add_api_route("/terminals/audit", self.terminal_audit, methods=["POST"])
        
        self.logger.info("✅ Client Manager plugin loaded")
    
    async def on_unload(self):
        """Cleanup при выгрузке."""
        # Stop embedded process if we started it
        try:
            if getattr(self, "_embedded_proc", None) and embed_helper is not None:
                embed_helper.stop_embedded()
                self.logger.info("🔌 Stopped embedded client-manager-service")
        except Exception:
            pass
        self.logger.info("👋 Client Manager plugin unloaded")
    
    # ============= Client Management Methods =============
    
    async def clients_list(self) -> JSONResponse:
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
    
    async def clients_list_compat(self) -> JSONResponse:
        """Compatibility endpoint."""
        return await self.clients_list()
    
    async def command_exec(self, client_id: str, payload: Dict[str, Any]) -> JSONResponse:
        """Execute command on client."""
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
    
    async def command_exec_compat(self, client_id: str, payload: Dict[str, Any]) -> JSONResponse:
        """Compatibility endpoint."""
        return await self.command_exec(client_id, payload)
    
    async def command_cancel(self, client_id: str, command_id: str) -> JSONResponse:
        """Cancel running command."""
        path = f"/api/commands/{client_id}/cancel?" + urlencode({"command_id": command_id})
        data = await _http_json("POST", path)
        return JSONResponse(data)
    
    async def command_cancel_compat(self, client_id: str, command_id: str) -> JSONResponse:
        """Compatibility endpoint."""
        return await self.command_cancel(client_id, command_id)
    
    async def commands_history(self) -> JSONResponse:
        """Get command execution history."""
        data = await _http_json("GET", "/api/commands/history")
        return JSONResponse(data)
    
    async def command_result(self, command_id: str) -> JSONResponse:
        """Get command execution result."""
        data = await _http_json("GET", f"/api/commands/{command_id}")
        return JSONResponse(data)
    
    async def client_install(self, client_id: str, payload: Dict[str, Any]) -> JSONResponse:
        """Trigger remote installation on agent."""
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

        try:
            async with get_session() as db:
                cid = f"install_{uuid.uuid4().hex}"
                log = CommandLog(id=cid, client_id=client_id, command="install_pty_manager", status="sent")
                await db.merge(log)
        except Exception:
            pass

        return JSONResponse({"ok": True, "forwarded": data})
    
    # ============= File Management Methods =============
    
    async def upload_file_from_browser(
        self,
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
    
    async def upload_init_proxy(self, request: Request):
        """Proxy endpoint for upload initialization."""
        content_type = request.headers.get('content-type', '')
        
        if content_type.startswith('multipart/form-data'):
            form = await request.form()
            client_id = form.get('client_id')
            dest_path = form.get('path') or form.get('dest_path')
            upload_file = form.get('file')
            if not client_id or not dest_path or not upload_file:
                raise HTTPException(status_code=400, detail='client_id, path и file обязательны')
            return await self.upload_file_from_browser(client_id=client_id, dest_path=dest_path, file=upload_file)

        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail='Invalid request body')
        
        try:
            data = await _http_json('POST', '/api/files/upload/init', body=body)
            return JSONResponse(data)
        except HTTPException as he:
            raise he
    
    async def transfer_status_proxy(self, transfer_id: str) -> JSONResponse:
        """Get transfer status."""
        data = await _http_json("GET", f"/api/files/transfers/{transfer_id}/status")
        return JSONResponse(data)
    
    async def transfer_pause_proxy(self, payload: Dict[str, Any]) -> JSONResponse:
        """Pause transfer."""
        data = await _http_json("POST", "/api/files/transfers/pause", body=payload)
        return JSONResponse(data)
    
    async def transfer_resume_proxy(self, payload: Dict[str, Any]) -> JSONResponse:
        """Resume transfer."""
        data = await _http_json("POST", "/api/files/transfers/resume", body=payload)
        return JSONResponse(data)
    
    async def transfer_cancel_proxy(self, payload: Dict[str, Any]) -> JSONResponse:
        """Cancel transfer."""
        data = await _http_json("POST", "/api/files/transfers/cancel", body=payload)
        return JSONResponse(data)
    
    async def initiate_download(self, client_id: str = Form(...), path: str = Form(...)) -> JSONResponse:
        """Initiate file download from client."""
        body = {"client_id": client_id, "path": path, "direction": "download"}
        data = await _http_json("POST", "/api/files/upload/init", body=body)
        return JSONResponse(data)
    
    async def proxy_download(self, transfer_id: str):
        """Proxy file download from client_manager."""
        base = os.getenv("CM_BASE_URL", "http://127.0.0.1:10000")
        base_url = base.rstrip('/')
        path = f"/api/files/transfers/{transfer_id}/download"
        full_url = f"{base_url}{path}"
        
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
    
    # ============= Enrollment Methods =============
    
    async def enrollments_pending(self) -> JSONResponse:
        """Get pending enrollment requests."""
        data = await _http_json("GET", "/api/enrollments/pending", headers=get_admin_headers())
        return JSONResponse(data)
    
    async def enrollments_pending_compat(self) -> JSONResponse:
        """Compatibility endpoint."""
        return await self.enrollments_pending()
    
    async def enroll_approve(self, client_id: str) -> JSONResponse:
        """Approve client enrollment."""
        data = await _http_json("POST", f"/api/enrollments/{client_id}/approve", headers=get_admin_headers())
        return JSONResponse(data)
    
    async def enroll_approve_compat(self, client_id: str) -> JSONResponse:
        """Compatibility endpoint."""
        return await self.enroll_approve(client_id)
    
    async def enroll_reject(self, client_id: str) -> JSONResponse:
        """Reject client enrollment."""
        data = await _http_json("POST", f"/api/enrollments/{client_id}/reject", headers=get_admin_headers())
        return JSONResponse(data)
    
    async def enroll_reject_compat(self, client_id: str) -> JSONResponse:
        """Compatibility endpoint."""
        return await self.enroll_reject(client_id)
    
    # ============= Terminal Audit Method =============
    
    async def terminal_audit(self, payload: Dict[str, Any]):
        """Create or update terminal audit entry."""
        sid = payload.get("session_id")
        if not sid:
            raise HTTPException(status_code=400, detail="session_id required")

        event = payload.get("event")
        ts = payload.get("ts")
        if ts:
            try:
                ts_val = datetime.fromtimestamp(float(ts))
            except Exception:
                ts_val = None
        else:
            ts_val = datetime.utcnow()

        async with get_session() as db:
            q = select(TerminalAudit).where(TerminalAudit.session_id == sid)
            result = await db.execute(q)
            res = result.scalar_one_or_none()
            
            if res is None:
                aid = payload.get("id") or f"term_{uuid.uuid4().hex}"
                rec = TerminalAudit(
                    id=aid,
                    session_id=sid,
                    client_id=payload.get("client_id"),
                    initiator_type=(payload.get("initiator") or {}).get("type"),
                    initiator_id=(payload.get("initiator") or {}).get("id"),
                    record_path=payload.get("record_path"),
                    started_at=ts_val if event == "started" else None,
                    stopped_at=ts_val if event == "stopped" else None,
                    exit_code=payload.get("exit_code")
                )
                await db.merge(rec)
            else:
                if event == "started":
                    res.started_at = ts_val
                if event == "stopped":
                    res.stopped_at = ts_val
                    res.exit_code = payload.get("exit_code")
                if payload.get("record_path"):
                    res.record_path = payload.get("record_path")
                if payload.get("initiator"):
                    res.initiator_type = (payload.get("initiator") or {}).get("type")
                    res.initiator_id = (payload.get("initiator") or {}).get("id")
                await db.merge(res)

        return JSONResponse({"status": "ok"})

