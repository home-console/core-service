"""
Admin interface routes.
Serves the main admin dashboard and terminal audit.
"""
import os
from typing import Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from sqlalchemy import select

# Terminal audit is now handled by client_manager plugin
# This route is kept for backward compatibility but will be removed
try:
    from ..core.database import get_session
    from ..plugins.client_manager.models import TerminalAudit
except ImportError:
    # Fallback if plugin not loaded
    TerminalAudit = None
    get_session = None  # type: ignore

router = APIRouter()


@router.get("/admin/events/logs")
async def get_event_logs(request: Request, limit: int = 100, filter: str = None):
    """
    Получить логи событий из event_bus.
    
    Args:
        limit: Максимальное количество записей (по умолчанию 100)
        filter: Фильтр по имени события (поддерживает wildcards, например "device.*")
    """
    try:
        from ..core import EventBus
        # Получаем event_bus из app.state
        if hasattr(request.app.state, 'event_bus'):
            event_bus = request.app.state.event_bus
        else:
            from ..core import get_event_bus as _get_event_bus
            event_bus = _get_event_bus(request)
        logs = event_bus.get_logs(limit=limit, event_filter=filter)
        return JSONResponse({
            "status": "ok",
            "data": {
                "logs": logs,
                "count": len(logs)
            }
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": str(e)
        }, status_code=500)


@router.get("/admin/events/stats")
async def get_event_stats(request: Request):
    """Получить статистику по событиям."""
    try:
        from ..core import EventBus
        # Получаем event_bus из app.state
        if hasattr(request.app.state, 'event_bus'):
            event_bus = request.app.state.event_bus
        else:
            from ..core import get_event_bus as _get_event_bus
            event_bus = _get_event_bus(request)
        stats = event_bus.get_stats()
        return JSONResponse({
            "status": "ok",
            "data": stats
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": str(e)
        }, status_code=500)


@router.post("/admin/events/clear")
async def clear_event_logs(request: Request):
    """Очистить лог событий."""
    try:
        from ..core import EventBus
        # Получаем event_bus из app.state
        if hasattr(request.app.state, 'event_bus'):
            event_bus = request.app.state.event_bus
        else:
            from ..core import get_event_bus as _get_event_bus
            event_bus = _get_event_bus(request)
        event_bus.clear_log()
        return JSONResponse({
            "status": "ok",
            "message": "Event log cleared"
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": str(e)
        }, status_code=500)


@router.get("/admin/logs")
async def get_application_logs(
    limit: int = 100,
    level: str = None,
    module: str = None,
    search: str = None,
    logger_name: str = None
):
    """
    Получить логи приложения (ядро, плагины и т.д.).
    
    Args:
        limit: Максимальное количество записей (по умолчанию 100)
        level: Фильтр по уровню (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        module: Фильтр по модулю (например, 'core_service', 'plugin')
        search: Поиск по сообщению
        logger_name: Фильтр по имени логгера
    """
    try:
        from ..utils.log_collector import application_log_collector
        
        if application_log_collector is None:
            return JSONResponse({
                "status": "error",
                "message": "Log collector not initialized"
            }, status_code=503)
        
        logs = application_log_collector.get_logs(
            limit=limit,
            level=level,
            module=module,
            search=search,
            logger_name=logger_name
        )
        
        return JSONResponse({
            "status": "ok",
            "data": {
                "logs": logs,
                "count": len(logs)
            }
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": str(e)
        }, status_code=500)


@router.get("/admin/logs/stats")
async def get_application_logs_stats():
    """Получить статистику по логам приложения."""
    try:
        from ..utils.log_collector import application_log_collector
        
        if application_log_collector is None:
            return JSONResponse({
                "status": "error",
                "message": "Log collector not initialized"
            }, status_code=503)
        
        stats = application_log_collector.get_stats()
        return JSONResponse({
            "status": "ok",
            "data": stats
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": str(e)
        }, status_code=500)


@router.post("/admin/logs/clear")
async def clear_application_logs():
    """Очистить логи приложения."""
    try:
        from ..utils.log_collector import application_log_collector
        
        if application_log_collector is None:
            return JSONResponse({
                "status": "error",
                "message": "Log collector not initialized"
            }, status_code=503)
        
        application_log_collector.clear()
        return JSONResponse({
            "status": "ok",
            "message": "Application logs cleared"
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": str(e)
        }, status_code=500)


@router.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Serve admin dashboard."""
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static')
    index_file = os.path.join(static_dir, 'admin.html')
    
    # If static file exists, serve it
    if os.path.exists(index_file):
        with open(index_file, 'r', encoding='utf-8') as f:
            return HTMLResponse(content=f.read())
    
    # Otherwise return inline version
    return HTMLResponse(content=get_inline_admin_html())


# Health endpoint is defined in app.py to avoid conflicts


@router.post("/terminals/audit")
async def terminal_audit(payload: Dict[str, Any]):
    """
    Create or update terminal audit entry.
    
    DEPRECATED: This endpoint is kept for backward compatibility.
    Use /api/terminals/audit from client_manager plugin instead.
    
    Payload: {
        "session_id": "...",
        "client_id": "...",
        "initiator": {"type": "user", "id": "alice"},
        "event": "started|stopped",
        "ts": 1234567890,
        "record_path": "/tmp/terminals/...",
        "exit_code": 0
    }
    """
    if TerminalAudit is None:
        raise HTTPException(
            status_code=503,
            detail="Terminal audit functionality is provided by client_manager plugin. Please ensure the plugin is loaded."
        )
    
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
            import uuid
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


def get_inline_admin_html() -> str:
    """Return inline admin HTML if static file doesn't exist."""
    return """<!doctype html>
<html>
<head>
    <meta charset="utf-8" />
    <title>Core Admin</title>
    <style>
        body { font-family: -apple-system, Arial, sans-serif; margin: 24px; }
        h1 { margin-bottom: 8px; }
        .card { border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
        .row { margin: 8px 0; }
        button { padding: 6px 10px; margin-right: 6px; cursor: pointer; }
        input { padding: 6px; margin-right: 6px; }
        code { background: #f3f4f6; padding: 2px 4px; border-radius: 4px; }
    </style>
</head>
<body>
    <h1>🏠 Core Admin Panel</h1>
    
    <div class="card">
        <h2>📊 System Status</h2>
        <div id="status">Loading...</div>
    </div>
    
    <div class="card">
        <h2>💻 Clients</h2>
        <div id="clients">Loading...</div>
    </div>
    
    <div class="card">
        <h2>📝 Command History</h2>
        <div id="history">Loading...</div>
    </div>
    
    <div class="card">
        <h2>🔐 Enrollments (TOFU)</h2>
        <div id="enrollments">Loading...</div>
    </div>

    <script>
        async function fetchJSON(path, opts) {
            const res = await fetch(path, opts);
            if (!res.ok) throw new Error(await res.text());
            return await res.json();
        }

        async function loadStatus() {
            try {
                const data = await fetchJSON('/health');
                document.getElementById('status').innerHTML = `
                    <div>✅ Service: ${data.service || 'running'}</div>
                    <div>📌 Version: ${data.version || 'unknown'}</div>
                `;
            } catch (e) {
                document.getElementById('status').innerHTML = '❌ Error loading status';
            }
        }

        async function loadClients() {
            try {
                const data = await fetchJSON('/api/clients');
                const el = document.getElementById('clients');
                if (!data || data.length === 0) {
                    el.innerHTML = 'No clients connected';
                    return;
                }
                el.innerHTML = data.map(c => `
                    <div class="row">
                        <b>${c.hostname || 'Unknown'}</b> 
                        <code>${c.id}</code> — 
                        ${c.status || 'unknown'}
                        <input id="cmd_${c.id}" placeholder="Command..." />
                        <button onclick="sendCmd('${c.id}')">Execute</button>
                    </div>
                `).join('');
            } catch (e) {
                document.getElementById('clients').innerHTML = 'Error loading clients';
            }
        }

        async function sendCmd(id) {
            const val = document.getElementById(`cmd_${id}`).value;
            if (!val) return;
            try {
                await fetchJSON(`/api/commands/${id}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({command: val})
                });
                alert('Command sent!');
                await loadHistory();
            } catch (e) {
                alert('Error: ' + e.message);
            }
        }

        async function loadHistory() {
            try {
                const items = await fetchJSON('/api/commands/history');
                const el = document.getElementById('history');
                if (!items || items.length === 0) {
                    el.innerHTML = 'No history';
                    return;
                }
                el.innerHTML = items.slice(-10).reverse().map(r => `
                    <div class="row">
                        <code>${r.command_id || r.id}</code> @ 
                        <b>${r.client_id}</b> — 
                        ${r.success ? '✅ success' : '❌ failed'}
                    </div>
                `).join('');
            } catch (e) {
                document.getElementById('history').innerHTML = 'Error loading history';
            }
        }

        async function loadEnrollments() {
            try {
                const data = await fetchJSON('/api/enrollments/pending');
                const el = document.getElementById('enrollments');
                if (!data || data.length === 0) {
                    el.innerHTML = 'No pending enrollments';
                    return;
                }
                el.innerHTML = data.map(e => `
                    <div class="row">
                        <code>${e.client_id || e.id}</code>
                        <button onclick="approve('${e.client_id || e.id}')">✅ Approve</button>
                        <button onclick="reject('${e.client_id || e.id}')">❌ Reject</button>
                    </div>
                `).join('');
            } catch (e) {
                document.getElementById('enrollments').innerHTML = 'Error (check ADMIN_TOKEN)';
            }
        }

        async function approve(id) {
            await fetchJSON(`/api/enrollments/${id}/approve`, {method: 'POST'});
            await loadEnrollments();
        }

        async function reject(id) {
            await fetchJSON(`/api/enrollments/${id}/reject`, {method: 'POST'});
            await loadEnrollments();
        }

        async function tick() {
            await Promise.all([loadStatus(), loadClients(), loadHistory(), loadEnrollments()]);
        }
        
        tick();
        setInterval(tick, 5000);
    </script>
</body>
</html>"""
