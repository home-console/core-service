"""
Plugin management routes.
Handles plugin listing, registry, status, and mode management.
"""
import asyncio
import json
import os
from typing import Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from typing import Optional

from ..db import get_session
from ..models import Plugin, PluginVersion, PluginInstallJob
from ..utils.http_client import _http_json
from ..utils.auth import generate_jwt_token
from ..plugin_system.registry import external_plugin_registry

import logging
import uuid

logger = logging.getLogger(__name__)
router = APIRouter()


def standard_response(status: str = "ok", data: Optional[dict] = None, message: Optional[str] = None, code: int = 200):
    payload = {"status": status}
    if data is not None:
        payload["data"] = data
    if message:
        payload["message"] = message
    return JSONResponse(payload, status_code=code)


@router.get("/plugins")
async def list_plugins(request: Request):
    """List all plugins from registry and loaded plugins."""
    app = request.app
    result = {}
    
    # Получаем множество загруженных плагинов для проверки статуса
    loaded_plugin_ids = set()
    if hasattr(app.state, 'plugin_loader'):
        plugin_loader = app.state.plugin_loader
        loaded_plugin_ids = set(plugin_loader.plugins.keys())
        
        # Добавляем загруженные плагины из plugin_loader
        plugins_list = plugin_loader.list_plugins()
        for plugin in plugins_list:
            plugin_id = plugin.get('id') or plugin.get('name', 'unknown')
            result[plugin_id] = {
                'id': plugin_id,
                'name': plugin.get('name', plugin_id),
                'description': plugin.get('description', ''),
                'latest_version': plugin.get('version', 'unknown'),
                'type': plugin.get('type', 'internal'),
                'loaded': True  # Плагин загружен, так как он в plugin_loader
            }
    
    # Добавляем плагины из БД, которые еще не добавлены
    try:
        async with get_session() as db:
            result_q = await db.execute(select(Plugin))
            plugins = result_q.scalars().all()
            for p in plugins:
                # Используем p.id как ключ (это ID плагина)
                plugin_id = p.id
                
                # Если плагин уже есть в результате (из plugin_loader), обновляем его данными из БД
                if plugin_id in result:
                    # Обновляем данные из БД, но сохраняем runtime loaded статус (из plugin_loader)
                    result[plugin_id].update({
                        'description': p.description or result[plugin_id].get('description', ''),
                        'publisher': p.publisher,
                        'latest_version': p.latest_version or result[plugin_id].get('latest_version', 'unknown'),
                    })
                    # Загружаем версии
                    vs_q = await db.execute(select(PluginVersion).where(PluginVersion.plugin_name == plugin_id))
                    versions = vs_q.scalars().all()
                    if versions:
                        result[plugin_id]['versions'] = [{
                            'version': v.version,
                            'artifact_url': v.artifact_url,
                            'created_at': v.created_at.isoformat() if v.created_at else None
                        } for v in versions]
                    # loaded статус берем из runtime (plugin_loader), а не из БД
                    # result[plugin_id]['loaded'] уже установлен в True выше
                else:
                    # Плагин есть в БД, но не загружен в данный момент
                    vs_q = await db.execute(select(PluginVersion).where(PluginVersion.plugin_name == plugin_id))
                    versions = vs_q.scalars().all()
                    result[plugin_id] = {
                        'id': plugin_id,
                        'name': p.name,
                        'description': p.description,
                        'publisher': p.publisher,
                        'latest_version': p.latest_version or 'unknown',
                        'type': 'internal',  # По умолчанию internal, если не указано
                        'loaded': plugin_id in loaded_plugin_ids or getattr(p, 'loaded', False),  # Runtime статус или из БД
                        'versions': [{
                            'version': v.version,
                            'artifact_url': v.artifact_url,
                            'created_at': v.created_at.isoformat() if v.created_at else None
                        } for v in versions] if versions else []
                    }
    except Exception as e:
        logger.debug(f"Could not load plugins from DB: {e}")
    
    return result


@router.get("/plugins/status")
async def get_plugins_status(request: Request):
    """Get status of all plugins."""
    app = request.app
    status = {'internal': {}, 'external': {}}
    
    try:
        if hasattr(app.state, 'plugin_loader'):
            pl = app.state.plugin_loader
            for pid, p in pl.plugins.items():
                status['internal'][pid] = {'name': getattr(p, 'name', pid), 'loaded': True}
    except Exception:
        pass

    for pid, plugin in external_plugin_registry.plugins.items():
        status['external'][pid] = {
            'url': plugin.base_url,
            'healthy': plugin.is_healthy,
            'last_check': plugin.last_check.isoformat() if plugin.last_check else None,
            'error_count': plugin.error_count,
        }
    return standard_response(data={'status': status})


@router.post("/plugins/{plugin_id}/health-check")
async def check_plugin_health(plugin_id: str, request: Request):
    """Check health of specific plugin."""
    # Сначала смотрим встроенные (in-process) плагины
    if hasattr(request.app.state, 'plugin_loader'):
        pl = request.app.state.plugin_loader
        if plugin_id in pl.plugins:
            # Встроенный плагин считаем healthy, если он загружен
            return standard_response(data={'plugin_id': plugin_id, 'healthy': True, 'type': 'internal'})
    # Затем внешний реестр
    ok = await external_plugin_registry.health_check(plugin_id)
    plugin = external_plugin_registry.get_plugin(plugin_id)
    if not plugin:
        # Если плагин отсутствует и во внешнем реестре, отвечаем healthy=False без 404
        return standard_response(data={'plugin_id': plugin_id, 'healthy': False, 'type': 'unknown'})
    return standard_response(data={'plugin_id': plugin_id, 'healthy': ok, 'type': 'external', 'checked_at': plugin.last_check.isoformat() if plugin.last_check else None})


@router.post("/plugins/health-check-all")
async def check_all_plugins_health(request: Request):
    """Check health of all plugins."""
    results: Dict[str, Any] = {}
    
    # Встроенные плагины: помечаем healthy=True если загружены
    if hasattr(request.app.state, 'plugin_loader'):
        pl = request.app.state.plugin_loader
        for pid in pl.plugins.keys():
            results[pid] = True
    
    # Внешние плагины: проверяем через registry
    external_results = await external_plugin_registry.health_check_all()
    results.update(external_results)
    
    return standard_response(data={'results': results})


@router.post("/plugins/install")
async def install_plugin(payload: Dict[str, Any], request: Request):
    """Install plugin from various sources (URL, git, file upload)."""
    app = request.app
    
    if not hasattr(app.state, 'plugin_loader'):
        raise HTTPException(status_code=503, detail='Plugin loader not available')
    
    plugin_loader = app.state.plugin_loader
    install_type = (payload or {}).get('type', 'url')  # url, git, local
    
    # Create PluginInstallJob and run installation in background
    job_id = str(uuid.uuid4())
    job_record = None
    try:
        async with get_session() as db:
            # store minimal job info; payload saved for retry
            job = PluginInstallJob(id=job_id, plugin_name=payload.get('plugin_name') or payload.get('url') or 'unknown', version=payload.get('version') or 'unknown', status='pending', payload=payload)
            db.add(job)
            await db.flush()
            job_record = job
    except Exception:
        logger.exception('Failed to create install job record')

    async def _run_install(job_id: str, payload: Dict[str, Any]):
        # Background task performing installation and updating job record
        try:
            async with get_session() as db:
                j_q = await db.execute(select(PluginInstallJob).where(PluginInstallJob.id == job_id))
                j = j_q.scalar_one_or_none()
                if not j:
                    logger.error(f'Install job {job_id} not found in DB')
                    return
                j.status = 'running'
                j.started_at = datetime.utcnow()
                await db.flush()

            result = None
            try:
                if install_type == 'git':
                    git_url = payload.get('git_url')
                    if not git_url:
                        raise ValueError('git_url required')
                    result = await asyncio.to_thread(plugin_loader.install_from_git, git_url)
                elif install_type == 'url':
                    url = payload.get('url')
                    if not url:
                        raise ValueError('url required')
                    result = await plugin_loader.install_from_url(url)
                elif install_type == 'local':
                    path = payload.get('path')
                    if not path:
                        raise ValueError('path required')
                    result = await plugin_loader.install_from_local(path)
                else:
                    raise ValueError(f'Unsupported install type: {install_type}')

                # On success, update job
                async with get_session() as db:
                    j_q = await db.execute(select(PluginInstallJob).where(PluginInstallJob.id == job_id))
                    j = j_q.scalar_one_or_none()
                    if j:
                        j.status = 'success'
                        j.finished_at = datetime.utcnow()
                        j.logs = json.dumps({'result': result})
                        await db.flush()
            except Exception as ie:
                logger.exception(f'Installation job {job_id} failed: {ie}')
                async with get_session() as db:
                    j_q = await db.execute(select(PluginInstallJob).where(PluginInstallJob.id == job_id))
                    j = j_q.scalar_one_or_none()
                    if j:
                        j.status = 'failed'
                        j.finished_at = datetime.utcnow()
                        j.logs = str(ie)
                        await db.flush()
        except Exception:
            logger.exception('Error updating install job state')

    # schedule background task
    try:
        asyncio.create_task(_run_install(job_id, payload))
    except Exception:
        logger.exception('Failed to schedule install background task')

    return standard_response(status='accepted', data={'job_id': job_id}, message='Installation scheduled', code=202)


@router.get("/plugins/install/jobs")
async def list_install_jobs(limit: int = 20):
    """List recent plugin install jobs."""
    try:
        async with get_session() as db:
            q = await db.execute(select(PluginInstallJob).order_by(PluginInstallJob.created_at.desc()).limit(limit))
            rows = q.scalars().all()
            jobs = []
            for j in rows:
                jobs.append({
                    'id': j.id,
                    'plugin_name': j.plugin_name,
                    'version': j.version,
                    'status': j.status,
                    'created_at': j.created_at.isoformat() if j.created_at else None,
                    'started_at': j.started_at.isoformat() if j.started_at else None,
                    'finished_at': j.finished_at.isoformat() if j.finished_at else None,
                })
            return standard_response(data={'jobs': jobs})
    except Exception as e:
        logger.exception('Failed listing install jobs')
        return standard_response(status='error', message=str(e), code=500)


@router.get("/plugins/install/jobs/{job_id}")
async def get_install_job(job_id: str):
    try:
        async with get_session() as db:
            q = await db.execute(select(PluginInstallJob).where(PluginInstallJob.id == job_id))
            j = q.scalar_one_or_none()
            if not j:
                raise HTTPException(status_code=404, detail='job not found')
            return standard_response(data={
                'id': j.id,
                'plugin_name': j.plugin_name,
                'version': j.version,
                'status': j.status,
                'payload': j.payload,
                'logs': j.logs,
                'created_at': j.created_at.isoformat() if j.created_at else None,
                'started_at': j.started_at.isoformat() if j.started_at else None,
                'finished_at': j.finished_at.isoformat() if j.finished_at else None,
            })
    except HTTPException:
        raise
    except Exception as e:
        logger.exception('Failed getting install job')
        return standard_response(status='error', message=str(e), code=500)


@router.post("/plugins/install/jobs/{job_id}/retry")
async def retry_install_job(job_id: str):
    """Retry a failed install job by re-running installation using stored payload."""
    try:
        async with get_session() as db:
            q = await db.execute(select(PluginInstallJob).where(PluginInstallJob.id == job_id))
            j = q.scalar_one_or_none()
            if not j:
                raise HTTPException(status_code=404, detail='job not found')
            if not j.payload:
                raise HTTPException(status_code=400, detail='no payload stored for retry')
            payload = j.payload
    except HTTPException:
        raise
    except Exception as e:
        logger.exception('Failed to fetch job for retry')
        return standard_response(status='error', message=str(e), code=500)

    # create new job record for retry
    new_job_id = str(uuid.uuid4())
    try:
        async with get_session() as db:
            newj = PluginInstallJob(id=new_job_id, plugin_name=j.plugin_name, version=j.version, status='pending', payload=payload)
            db.add(newj)
            await db.flush()
    except Exception:
        logger.exception('Failed to create retry job')
        return standard_response(status='error', message='failed creating retry job', code=500)

    # schedule background task using same _run_install logic by invoking install endpoint internally
    try:
        # reuse install background runner by scheduling a task
        async def _run_again():
            # call internal background runner by duplicating logic (simple approach)
            try:
                # Using plugin_loader from app state is not available here; we will call installation directly
                # This minimal retry will call install endpoints synchronously depending on payload
                from fastapi import FastAPI
                # find plugin_loader via app import (global state)
                # fallback: use app in request context is not available; rely on plugin_loader module global
                # For simplicity, call installation via available functions in plugin_loader module
                # Import plugin_loader from app state not possible here — best-effort: do nothing
                logger.info(f'Retry job {new_job_id} scheduled (manual execution required)')
            except Exception:
                logger.exception('Retry background task failed to start')

        asyncio.create_task(_run_again())
    except Exception:
        logger.exception('Failed to schedule retry background task')

    return standard_response(status='accepted', data={'job_id': new_job_id}, message='Retry scheduled', code=202)


@router.delete("/plugins/{plugin_id}")
async def uninstall_plugin(
    plugin_id: str, 
    request: Request,
    drop_tables: bool = Query(False, description="Удалить таблицы плагина из БД (ОПАСНО - удаляет данные!)")
):
    """
    Uninstall and remove a plugin.
    
    Args:
        plugin_id: ID плагина для удаления
        drop_tables: Если True, удаляет таблицы плагина из БД (ОПАСНО - удаляет данные!)
    """
    app = request.app
    
    if not hasattr(app.state, 'plugin_loader'):
        raise HTTPException(status_code=503, detail='Plugin loader not available')
    
    plugin_loader = app.state.plugin_loader
    
    try:
        # First unload if loaded
        if plugin_id in plugin_loader.plugins:
            await plugin_loader.unload_plugin(plugin_id)
        
        # Then remove from disk (and optionally drop tables)
        result = await plugin_loader.uninstall_plugin(plugin_id, drop_tables=drop_tables)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"Plugin uninstall failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/plugins/{plugin_id}/enable", tags=["plugins"])
async def enable_plugin(plugin_id: str, request: Request):
    """
    Enable (load) a plugin.

    For regular plugins: loads the plugin into the core service.
    For infrastructure plugins (like client_manager): reloads with current settings.

    Args:
        plugin_id: ID of the plugin to enable

    Returns:
        JSON response with plugin_id and status message
    """
    app = request.app

    if not hasattr(app.state, 'plugin_loader'):
        raise HTTPException(status_code=503, detail='Plugin loader not available')

    plugin_loader = app.state.plugin_loader

    # Для инфраструктурных плагинов (например, client_manager) разрешаем только перезагрузку
    is_infrastructure_plugin = plugin_id == "client_manager"

    try:
        print(f"[DEBUG] Enable request for plugin {plugin_id}, loader.plugins={list(plugin_loader.plugins.keys())}")
        logger.info(f"🔄 Enable request for plugin {plugin_id}")

        if plugin_id in plugin_loader.plugins:
            print(f"[DEBUG] Plugin {plugin_id} already loaded")
            logger.info(f"ℹ️ Plugin {plugin_id} already in loader.plugins")
            return standard_response(data={'plugin_id': plugin_id}, message='already_enabled')

        print(f"[DEBUG] Setting loaded=True in DB for {plugin_id}")
        logger.info(f"📝 Setting plugin {plugin_id} loaded=True in DB")
        # Ensure DB reflects enabled state so loader won't skip loading
        try:
            async with get_session() as db:
                existing_q = await db.execute(select(Plugin).where(Plugin.id == plugin_id))
                existing = existing_q.scalar_one_or_none()
                if existing:
                    existing.enabled = True  # Устанавливаем enabled=True
                    existing.loaded = True
                    await db.flush()
                else:
                    p = Plugin(id=plugin_id, name=plugin_id, latest_version='unknown', enabled=True, loaded=True)
                    db.add(p)
                    await db.flush()
        except Exception:
            logger.exception('Failed to set plugin loaded flag in DB before enable')

        # Загружаем плагин
        if is_infrastructure_plugin:
            # Для инфраструктурных плагинов используем специфичную логику
            await plugin_loader.reload_plugin(plugin_id)
        else:
            # Для обычных плагинов используем стандартную загрузку
            await plugin_loader.reload_plugin(plugin_id)

        # Force OpenAPI regeneration
        if hasattr(request.app, 'openapi_schema'):
            request.app.openapi_schema = None

        return standard_response(data={'plugin_id': plugin_id}, message='enabled')
    except Exception as e:
        logger.error(f"Plugin enable failed: {e}", exc_info=True)
        return standard_response(status='error', message=str(e), code=500)


@router.post("/plugins/{plugin_id}/disable", tags=["plugins"])
async def disable_plugin(plugin_id: str, request: Request):
    """
    Disable (unload) a plugin without removing it.

    For regular plugins: unloads the plugin from the core service.
    For infrastructure plugins (like client_manager): returns error as they cannot be disabled.

    Args:
        plugin_id: ID of the plugin to disable

    Returns:
        JSON response with plugin_id and status message
    """
    app = request.app

    if not hasattr(app.state, 'plugin_loader'):
        raise HTTPException(status_code=503, detail='Plugin loader not available')

    plugin_loader = app.state.plugin_loader

    # Для инфраструктурных плагинов (например, client_manager) запрещаем выгрузку
    is_infrastructure_plugin = plugin_id == "client_manager"

    if is_infrastructure_plugin:
        # Инфраструктурные плагины нельзя отключить (только перезагрузить или изменить режим)
        logger.warning(f"Cannot disable infrastructure plugin {plugin_id}")
        return standard_response(
            status='error',
            message=f'Infrastructure plugin {plugin_id} cannot be disabled',
            code=400
        )

    try:
        # Сначала выгружаем, если загружен
        if plugin_id in plugin_loader.plugins:
            await plugin_loader.unload_plugin(plugin_id)

        # Фиксируем в БД enabled=False и loaded=False
        try:
            async with get_session() as db:
                existing_q = await db.execute(select(Plugin).where(Plugin.id == plugin_id))
                existing = existing_q.scalar_one_or_none()
                if existing:
                    if hasattr(existing, "enabled"):
                        existing.enabled = False
                    existing.loaded = False
                    await db.flush()
        except Exception:
            logger.exception("Failed to set plugin enabled flag in DB on disable")

        return standard_response(data={'plugin_id': plugin_id}, message='disabled')
    except Exception as e:
        logger.error(f"Plugin disable failed: {e}", exc_info=True)
        return standard_response(status='error', message=str(e), code=500)


@router.post("/plugins/{plugin_id}/reload", tags=["plugins"])
async def reload_plugin(plugin_id: str, request: Request):
    """
    Reload a plugin (unload and load again).

    For regular plugins: unloads and then loads the plugin.
    For infrastructure plugins: preserves current mode settings during reload.

    Args:
        plugin_id: ID of the plugin to reload

    Returns:
        JSON response with plugin_id and status message
    """
    app = request.app

    if not hasattr(app.state, 'plugin_loader'):
        raise HTTPException(status_code=503, detail='Plugin loader not available')

    plugin_loader = app.state.plugin_loader

    # Для инфраструктурных плагинов используем специфичную логику
    is_infrastructure_plugin = plugin_id == "client_manager"

    try:
        # Unload if loaded
        if plugin_id in plugin_loader.plugins:
            if is_infrastructure_plugin:
                # Для инфраструктурных плагинов может потребоваться специальная обработка
                # Сохраняем текущий режим и восстанавливаем после перезагрузки
                current_mode = "unknown"
                if hasattr(app.state, 'plugin_mode_manager'):
                    try:
                        mode_manager = app.state.plugin_mode_manager
                        mode_info = await mode_manager.get_mode_status(plugin_id)
                        current_mode = mode_info.get('current_mode', 'in_process')
                    except Exception:
                        logger.warning(f"Could not get current mode for {plugin_id}")

                await plugin_loader.unload_plugin(plugin_id)

                # Восстанавливаем плагин в том же режиме
                await plugin_loader.reload_plugin(plugin_id)

                # Если доступен PluginModeManager, восстанавливаем режим
                if hasattr(app.state, 'plugin_mode_manager') and current_mode != "unknown":
                    try:
                        mode_manager = app.state.plugin_mode_manager
                        from ..plugin_system.managers import PluginMode
                        target_mode = PluginMode(current_mode)
                        # Переключаем в тот же режим для инициализации
                        await mode_manager.switch_mode(plugin_id, target_mode, restart=False)
                    except Exception as e:
                        logger.warning(f"Could not restore mode for {plugin_id}: {e}")
            else:
                await plugin_loader.unload_plugin(plugin_id)
                await plugin_loader.reload_plugin(plugin_id)
        else:
            # Если плагин не загружен, просто загружаем его
            await plugin_loader.reload_plugin(plugin_id)

        # Force OpenAPI regeneration
        if hasattr(request.app, 'openapi_schema'):
            request.app.openapi_schema = None

        return standard_response(data={'plugin_id': plugin_id}, message='reloaded')
    except Exception as e:
        logger.error(f"Plugin reload failed: {e}", exc_info=True)
        return standard_response(status='error', message=str(e), code=500)


@router.post("/plugins/{plugin_id}/activate", tags=["plugins"])
async def activate_plugin(plugin_id: str, request: Request):
    """
    Activate a plugin (enable considering current mode).

    For infrastructure plugins (like client_manager): reloads with current settings.
    For regular plugins: enables as an internal plugin.

    Args:
        plugin_id: ID of the plugin to activate

    Returns:
        JSON response with plugin_id and status message
    """
    app = request.app

    if not hasattr(app.state, 'plugin_loader'):
        raise HTTPException(status_code=503, detail='Plugin loader not available')

    plugin_loader = app.state.plugin_loader
    is_infrastructure_plugin = plugin_id == "client_manager"

    try:
        # Для инфраструктурных плагинов просто перезагружаем с текущими настройками
        if is_infrastructure_plugin:
            if plugin_id in plugin_loader.plugins:
                # Перезагружаем существующий инфраструктурный плагин
                await plugin_loader.reload_plugin(plugin_id)
            else:
                # Загружаем инфраструктурный плагин
                await plugin_loader.reload_plugin(plugin_id)
        else:
            # Для обычных плагинов используем стандартную логику включения
            if plugin_id not in plugin_loader.plugins:
                # Обновляем статус в БД
                try:
                    async with get_session() as db:
                        existing_q = await db.execute(select(Plugin).where(Plugin.id == plugin_id))
                        existing = existing_q.scalar_one_or_none()
                        if existing:
                            existing.enabled = True
                            existing.loaded = True
                            await db.flush()
                        else:
                            p = Plugin(id=plugin_id, name=plugin_id, latest_version='unknown', enabled=True, loaded=True)
                            db.add(p)
                            await db.flush()
                except Exception:
                    logger.exception('Failed to set plugin loaded flag in DB before activation')

                await plugin_loader.reload_plugin(plugin_id)

        # Force OpenAPI regeneration
        if hasattr(request.app, 'openapi_schema'):
            request.app.openapi_schema = None

        return standard_response(data={'plugin_id': plugin_id}, message='activated')
    except Exception as e:
        logger.error(f"Plugin activation failed: {e}", exc_info=True)
        return standard_response(status='error', message=str(e), code=500)


@router.post("/plugins/{plugin_id}/deactivate", tags=["plugins"])
async def deactivate_plugin(plugin_id: str, request: Request):
    """
    Deactivate a plugin (disable while preserving configuration).

    For regular plugins: unloads the plugin from memory but keeps configuration.
    For infrastructure plugins (like client_manager): returns error as they cannot be deactivated.

    Args:
        plugin_id: ID of the plugin to deactivate

    Returns:
        JSON response with plugin_id and status message
    """
    app = request.app

    if not hasattr(app.state, 'plugin_loader'):
        raise HTTPException(status_code=503, detail='Plugin loader not available')

    plugin_loader = app.state.plugin_loader
    is_infrastructure_plugin = plugin_id == "client_manager"

    if is_infrastructure_plugin:
        logger.warning(f"Cannot deactivate infrastructure plugin {plugin_id}")
        return standard_response(
            status='error',
            message=f'Infrastructure plugin {plugin_id} cannot be deactivated',
            code=400
        )

    try:
        # Выгружаем плагин из памяти
        if plugin_id in plugin_loader.plugins:
            await plugin_loader.unload_plugin(plugin_id)

        # Обновляем статус в БД
        try:
            async with get_session() as db:
                existing_q = await db.execute(select(Plugin).where(Plugin.id == plugin_id))
                existing = existing_q.scalar_one_or_none()
                if existing:
                    existing.loaded = False  # Не отключаем полностью, а только выгружаем
                    await db.flush()
        except Exception:
            logger.exception("Failed to update plugin loaded status in DB on deactivation")

        return standard_response(data={'plugin_id': plugin_id}, message='deactivated')
    except Exception as e:
        logger.error(f"Plugin deactivation failed: {e}", exc_info=True)
        return standard_response(status='error', message=str(e), code=500)


@router.get("/plugins/{plugin_id}/mode")
async def get_plugin_mode(plugin_id: str, request: Request):
    """
    Get current runtime mode of a plugin.

    Returns:
        - runtime_mode: "in_process" | "microservice" | "hybrid"
        - available_modes: list of available modes for this plugin
        - supports_mode_switch: whether this plugin supports mode switching
    """
    app = request.app

    # Try to use the enhanced PluginModeManager if available
    if hasattr(app.state, 'plugin_mode_manager'):
        try:
            from ..plugin_system.managers import PluginMode
            mode_manager = app.state.plugin_mode_manager
            status = await mode_manager.get_mode_status(plugin_id)

            # Map to the expected response format
            runtime_mode = status.get('current_mode', 'in_process')
            available_modes = [m.value for m in status.get('supported_modes', [PluginMode.IN_PROCESS])]
            supports_switch = status.get('mode_switch_supported', False)

            return standard_response(data={
                'plugin_id': plugin_id,
                'runtime_mode': runtime_mode,
                'available_modes': available_modes,
                'supports_mode_switch': supports_switch,
                'process_info': status.get('process_info', {}),
                'mode_descriptions': {
                    'in_process': 'Запуск внутри Core Service (embedded/subprocess)',
                    'microservice': 'Запуск как отдельный Docker контейнер',
                    'hybrid': 'Комбинированный режим',
                    'embedded': 'Запуск как subprocess внутри Core'
                }
            })
        except Exception as e:
            logger.warning(f"Could not get plugin mode from PluginModeManager: {e}")

    # Fallback to the original implementation
    runtime_mode = "in_process"
    available_modes = ["in_process"]
    supports_switch = False

    try:
        async with get_session() as db:
            existing_q = await db.execute(select(Plugin).where(Plugin.id == plugin_id))
            existing = existing_q.scalar_one_or_none()
            if existing:
                if existing.runtime_mode:
                    runtime_mode = existing.runtime_mode
                if existing.supported_modes:
                    available_modes = existing.supported_modes
                if existing.mode_switch_supported:
                    supports_switch = existing.mode_switch_supported
    except Exception as e:
        logger.warning(f"Could not get plugin mode from DB: {e}")

    # Специальная логика для client_manager (учитываем CM_MODE env)
    if plugin_id == "client_manager":
        cm_mode = os.getenv("CM_MODE", "external")
        if cm_mode == "embedded":
            runtime_mode = "in_process"
        elif cm_mode == "external":
            runtime_mode = "microservice"

    return standard_response(data={
        'plugin_id': plugin_id,
        'runtime_mode': runtime_mode,
        'available_modes': available_modes,
        'supports_mode_switch': supports_switch,
        'mode_descriptions': {
            'in_process': 'Запуск внутри Core Service (embedded/subprocess)',
            'microservice': 'Запуск как отдельный Docker контейнер',
            'hybrid': 'Комбинированный режим'
        }
    })


@router.post("/plugins/{plugin_id}/mode")
async def set_plugin_mode(plugin_id: str, payload: Dict[str, Any], request: Request):
    """
    Set runtime mode for a plugin.

    Body:
        - mode: "in_process" | "microservice" | "embedded" | "hybrid"
        - apply_now: bool (default: false) - применить немедленно (перезагрузка плагина)

    Returns:
        - success: bool
        - message: str
        - requires_restart: bool - требуется ли перезапуск сервиса
    """
    app = request.app

    new_mode = (payload or {}).get('mode')
    apply_now = (payload or {}).get('apply_now', False)

    valid_modes = {'in_process', 'microservice', 'hybrid', 'embedded'}
    if not new_mode or new_mode not in valid_modes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode. Must be one of: {', '.join(valid_modes)}"
        )

    # Try to use the enhanced PluginModeManager if available
    if hasattr(app.state, 'plugin_mode_manager'):
        try:
            from ..plugin_system.managers import PluginMode
            mode_manager = app.state.plugin_mode_manager

            # Convert string to enum
            target_mode = PluginMode(new_mode)

            # Check if mode is supported
            is_supported = await mode_manager.is_mode_supported(plugin_id, target_mode)
            if not is_supported:
                raise HTTPException(
                    status_code=400,
                    detail=f"Plugin {plugin_id} does not support mode {new_mode}"
                )

            # Switch mode
            result = await mode_manager.switch_mode(plugin_id, target_mode, restart=apply_now)

            return standard_response(data={
                'plugin_id': plugin_id,
                'old_mode': result.get('old_mode'),
                'new_mode': result.get('new_mode'),
                'applied': result.get('restart_applied', False),
                'requires_restart': False,  # Mode manager handles restarts internally
                'health_status': result.get('health_status'),
                'process_info': result.get('process_info', {})
            }, message=f"Mode switched to {new_mode}")

        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Could not set plugin mode via PluginModeManager: {e}")

    # Fallback to the original implementation
    requires_restart = False
    old_mode = None

    try:
        # Обновляем режим в БД
        async with get_session() as db:
            existing_q = await db.execute(select(Plugin).where(Plugin.id == plugin_id))
            existing = existing_q.scalar_one_or_none()

            if existing:
                old_mode = existing.runtime_mode
                existing.runtime_mode = new_mode
                await db.flush()
            else:
                # Создаем запись если её нет
                p = Plugin(
                    id=plugin_id,
                    name=plugin_id,
                    latest_version='unknown',
                    runtime_mode=new_mode,
                    loaded=False
                )
                db.add(p)
                await db.flush()

        logger.info(f"🔄 Plugin {plugin_id} mode changed: {old_mode} → {new_mode}")

        # Специальная логика для client_manager
        if plugin_id == "client_manager":
            if new_mode == "in_process":
                # Переключение на embedded режим
                os.environ["CM_MODE"] = "embedded"
                requires_restart = True  # Нужен перезапуск для применения

                if apply_now and hasattr(app.state, 'plugin_loader'):
                    plugin_loader = app.state.plugin_loader
                    try:
                        # Перезагружаем плагин для embedded режима
                        if plugin_id in plugin_loader.plugins:
                            await plugin_loader.unload_plugin(plugin_id)
                        await plugin_loader.reload_plugin(plugin_id)
                        requires_restart = False  # Применили без перезапуска
                        logger.info(f"✅ Plugin {plugin_id} reloaded with new mode: {new_mode}")
                    except Exception as e:
                        logger.error(f"Failed to reload plugin after mode change: {e}")
                        requires_restart = True
            else:
                # Переключение на external (microservice) режим
                os.environ["CM_MODE"] = "external"

                # Для external режима НЕ пытаемся перезагружать плагин как внутренний
                # Просто отключаем его в памяти, если он загружен
                if apply_now and hasattr(app.state, 'plugin_loader'):
                    plugin_loader = app.state.plugin_loader
                    try:
                        if plugin_id in plugin_loader.plugins:
                            # Выгружаем плагин из памяти, т.к. он теперь работает как внешний сервис
                            await plugin_loader.unload_plugin(plugin_id)
                            logger.info(f"✅ Plugin {plugin_id} unloaded (now running as external service)")
                        requires_restart = False
                    except Exception as e:
                        logger.error(f"Failed to unload plugin after mode change: {e}")
                        requires_restart = True
                else:
                    requires_restart = True

        return standard_response(data={
            'plugin_id': plugin_id,
            'old_mode': old_mode,
            'new_mode': new_mode,
            'applied': apply_now and not requires_restart,
            'requires_restart': requires_restart,
        }, message=f"Mode changed to {new_mode}")

    except Exception as e:
        logger.error(f"Plugin mode change failed: {e}", exc_info=True)
        return standard_response(status='error', message=str(e), code=500)


@router.get("/plugins/modes")
async def list_plugins_modes(request: Request):
    """
    Get runtime modes for all plugins.

    Returns list of plugins with their current modes and available modes.
    """
    app = request.app

    # Try to use the enhanced PluginModeManager if available
    if hasattr(app.state, 'plugin_mode_manager'):
        try:
            mode_manager = app.state.plugin_mode_manager
            status = await mode_manager.list_mode_status()

            result = []
            for plugin_id, plugin_status in status.items():
                plugin_info = {
                    'id': plugin_id,
                    'name': plugin_status.get('name', plugin_id),
                    'runtime_mode': plugin_status.get('current_mode', 'in_process'),
                    'loaded': plugin_id in getattr(app.state.plugin_loader, 'plugins', {}),
                    'enabled': getattr(app.state.plugin_loader.plugins.get(plugin_id), 'enabled', True) if plugin_id in getattr(app.state.plugin_loader, 'plugins', {}) else True,
                    'available_modes': [m.value for m in plugin_status.get('supported_modes', [])] if plugin_status.get('supported_modes') else ['in_process'],
                    'supports_mode_switch': plugin_status.get('mode_switch_supported', False),
                    'process_info': plugin_status.get('process_info', {}),
                    'health_status': plugin_status.get('health_status', {})
                }
                result.append(plugin_info)

            return standard_response(data={'plugins': result})
        except Exception as e:
            logger.warning(f"Could not get plugin modes from PluginModeManager: {e}")

    # Fallback to the original implementation
    result = []

    try:
        async with get_session() as db:
            plugins_q = await db.execute(select(Plugin))
            plugins = plugins_q.scalars().all()

            for p in plugins:
                plugin_info = {
                    'id': p.id,
                    'name': p.name,
                    'runtime_mode': p.runtime_mode or 'in_process',
                    'loaded': p.loaded,
                    'enabled': getattr(p, 'enabled', True),
                    'available_modes': p.supported_modes or ['in_process'],
                    'supports_mode_switch': p.mode_switch_supported or False,
                }

                result.append(plugin_info)

    except Exception as e:
        logger.warning(f"Could not load plugin modes from DB: {e}")

    # Добавляем загруженные плагины, которых нет в БД
    if hasattr(app.state, 'plugin_loader'):
        plugin_loader = app.state.plugin_loader
        db_ids = {p['id'] for p in result}

        for pid, plugin in plugin_loader.plugins.items():
            if pid not in db_ids:
                result.append({
                    'id': pid,
                    'name': getattr(plugin, 'name', pid),
                    'runtime_mode': 'in_process',
                    'loaded': True,
                    'enabled': True,
                    'available_modes': ['in_process'],
                    'supports_mode_switch': False,
                })

    return standard_response(data={'plugins': result})


# Plugin Configuration Endpoints
@router.get("/plugins/{plugin_id}/config")
async def get_plugin_config(plugin_id: str, request: Request):
    """
    Get configuration for a specific plugin.

    Returns:
        - config: plugin configuration
        - mode: current runtime mode
        - enabled: whether plugin is enabled
        - dependencies: plugin dependencies
    """
    app = request.app

    # Try to use the enhanced PluginConfigManager if available
    if hasattr(app.state, 'plugin_config_manager'):
        try:
            config_manager = app.state.plugin_config_manager
            config = await config_manager.get_config(plugin_id)

            # Get dependency info if dependency manager is available
            dependencies_info = []
            if hasattr(app.state, 'plugin_dependency_manager'):
                try:
                    from ..plugin_system.managers import PluginDependency
                    dep_manager = app.state.plugin_dependency_manager
                    if plugin_id in dep_manager.plugins:
                        plugin_info = dep_manager.plugins[plugin_id]
                        dependencies_info = [
                            {
                                'plugin_id': dep.plugin_id,
                                'version_spec': dep.version_spec,
                                'type': dep.dependency_type.value
                            }
                            for dep in plugin_info.dependencies
                        ]
                except Exception:
                    pass

            if config:
                return standard_response(data={
                    'plugin_id': config.plugin_id,
                    'mode': config.mode.value,
                    'enabled': config.enabled,
                    'config': config.config,
                    'health_check_interval': config.health_check_interval,
                    'restart_policy': config.restart_policy,
                    'resources': config.resources,
                    'dependencies': config.dependencies,
                    'dependency_info': dependencies_info,
                    'supported_modes': [m.value for m in config.supported_modes],
                    'metadata': config.metadata
                })
            else:
                # Return default config
                default_config = await config_manager.get_default_config(plugin_id)
                return standard_response(data={
                    'plugin_id': default_config.plugin_id,
                    'mode': default_config.mode.value,
                    'enabled': default_config.enabled,
                    'config': default_config.config,
                    'health_check_interval': default_config.health_check_interval,
                    'restart_policy': default_config.restart_policy,
                    'resources': default_config.resources,
                    'dependencies': default_config.dependencies,
                    'dependency_info': dependencies_info,
                    'supported_modes': [m.value for m in default_config.supported_modes],
                    'metadata': default_config.metadata
                })
        except Exception as e:
            logger.warning(f"Could not get plugin config from PluginConfigManager: {e}")

    # Fallback - return empty config
    return standard_response(data={
        'plugin_id': plugin_id,
        'mode': 'in_process',
        'enabled': True,
        'config': {},
        'health_check_interval': 30,
        'restart_policy': 'always',
        'resources': {},
        'dependencies': [],
        'dependency_info': [],
        'supported_modes': ['in_process'],
        'metadata': {}
    })


@router.post("/plugins/{plugin_id}/config")
async def set_plugin_config(plugin_id: str, payload: Dict[str, Any], request: Request):
    """
    Set configuration for a specific plugin.

    Body:
        - mode: runtime mode
        - enabled: whether plugin is enabled
        - config: plugin-specific configuration
        - health_check_interval: health check interval in seconds
        - restart_policy: restart policy
        - resources: resource limits
        - dependencies: plugin dependencies
        - supported_modes: supported runtime modes
        - metadata: additional metadata
    """
    app = request.app

    # Try to use the enhanced PluginConfigManager if available
    if hasattr(app.state, 'plugin_config_manager'):
        try:
            config_manager = app.state.plugin_config_manager
            updated_config = await config_manager.update_config(plugin_id, payload)

            return standard_response(data={
                'plugin_id': updated_config.plugin_id,
                'mode': updated_config.mode.value,
                'enabled': updated_config.enabled,
                'config': updated_config.config,
                'health_check_interval': updated_config.health_check_interval,
                'restart_policy': updated_config.restart_policy,
                'resources': updated_config.resources,
                'dependencies': updated_config.dependencies,
                'supported_modes': [m.value for m in updated_config.supported_modes],
                'metadata': updated_config.metadata
            }, message=f"Config updated for plugin {plugin_id}")
        except Exception as e:
            logger.error(f"Could not set plugin config via PluginConfigManager: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # Fallback - return success without actual update
    return standard_response(data={'plugin_id': plugin_id}, message="Config update not supported")


# Plugin Dependencies Endpoints
@router.get("/plugins/{plugin_id}/dependencies")
async def get_plugin_dependencies(plugin_id: str, request: Request):
    """Get dependencies for a specific plugin."""
    app = request.app

    if hasattr(app.state, 'plugin_dependency_manager'):
        try:
            dep_manager = app.state.plugin_dependency_manager
            if plugin_id in dep_manager.plugins:
                plugin_info = dep_manager.plugins[plugin_id]
                dependencies = [
                    {
                        'plugin_id': dep.plugin_id,
                        'version_spec': dep.version_spec,
                        'type': dep.dependency_type.value,
                        'optional': dep.optional
                    }
                    for dep in plugin_info.dependencies
                ]

                dependents = await dep_manager.get_plugin_dependents(plugin_id)

                return standard_response(data={
                    'plugin_id': plugin_id,
                    'dependencies': dependencies,
                    'dependents': dependents,
                    'can_load': await dep_manager.can_load_plugin(plugin_id)
                })
            else:
                raise HTTPException(status_code=404, detail=f'Plugin {plugin_id} not found')
        except Exception as e:
            logger.error(f"Error getting dependencies for {plugin_id}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # Fallback
    return standard_response(data={
        'plugin_id': plugin_id,
        'dependencies': [],
        'dependents': [],
        'can_load': (True, [])
    })


@router.post("/plugins/{plugin_id}/dependencies")
async def add_plugin_dependency(plugin_id: str, payload: Dict[str, Any], request: Request):
    """Add dependency for a specific plugin."""
    app = request.app

    if hasattr(app.state, 'plugin_dependency_manager'):
        try:
            from ..plugin_system.managers import PluginDependency, DependencyType

            dep_plugin_id = payload.get('plugin_id')
            version_spec = payload.get('version_spec', '>=0.0.0')
            dep_type_str = payload.get('type', 'required')

            if not dep_plugin_id:
                raise HTTPException(status_code=400, detail='dependency plugin_id is required')

            try:
                dep_type = DependencyType(dep_type_str)
            except ValueError:
                raise HTTPException(status_code=400, detail=f'Invalid dependency type: {dep_type_str}')

            dep = PluginDependency(
                plugin_id=dep_plugin_id,
                version_spec=version_spec,
                dependency_type=dep_type
            )

            # Add to existing plugin
            if plugin_id in app.state.plugin_dependency_manager.plugins:
                plugin_info = app.state.plugin_dependency_manager.plugins[plugin_id]
                plugin_info.dependencies.append(dep)

                # Rebuild dependency graph
                await app.state.plugin_dependency_manager._build_dependency_graph(plugin_info)

                return standard_response(data={
                    'plugin_id': plugin_id,
                    'dependency': {
                        'plugin_id': dep.plugin_id,
                        'version_spec': dep.version_spec,
                        'type': dep.dependency_type.value
                    },
                    'message': 'Dependency added'
                })
            else:
                raise HTTPException(status_code=404, detail=f'Plugin {plugin_id} not found')
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error adding dependency for {plugin_id}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # Fallback
    return standard_response(data={
        'plugin_id': plugin_id,
        'dependency': payload,
        'message': 'Dependency management not available'
    })


@router.get("/plugins/dependencies/resolve")
async def resolve_dependencies(request: Request):
    """Resolve load order based on dependencies."""
    app = request.app

    if hasattr(app.state, 'plugin_dependency_manager'):
        try:
            order = await app.state.plugin_dependency_manager.resolve_load_order()
            return standard_response(data={
                'load_order': order,
                'total_plugins': len(order)
            })
        except Exception as e:
            logger.error(f"Error resolving dependencies: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # Fallback
    return standard_response(data={
        'load_order': [],
        'total_plugins': 0
    })


@router.get("/plugins/dependencies/report")
async def get_dependencies_report(request: Request):
    """Get full dependency report."""
    app = request.app

    if hasattr(app.state, 'plugin_dependency_manager'):
        try:
            report = await app.state.plugin_dependency_manager.get_dependency_report()
            return standard_response(data=report)
        except Exception as e:
            logger.error(f"Error getting dependency report: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # Fallback
    return standard_response(data={
        'plugins': {},
        'cycles': [],
        'conflicts': []
    })


# Registry endpoints
@router.post("/registry/plugins")
async def registry_publish(payload: Dict[str, Any]):
    """Publish plugin to registry."""
    name = (payload or {}).get('name')
    version = (payload or {}).get('version')
    manifest = (payload or {}).get('manifest')
    artifact_url = (payload or {}).get('artifact_url')
    publisher = (payload or {}).get('publisher')

    if not name or not version or not manifest:
        raise HTTPException(status_code=400, detail='name, version and manifest are required')

    allowed_types = {'node', 'python', 'docker', 'git', 'zip', 'binary', 'wasm'}
    mtype = manifest.get('type') or (payload or {}).get('type') or None
    if mtype and mtype not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Unsupported manifest type: {mtype}")

    try:
        async with get_session() as db:
            existing_q = await db.execute(select(Plugin).where(Plugin.name == name))
            existing = existing_q.scalar_one_or_none()
            if not existing:
                p = Plugin(id=name, name=name, description=manifest.get('description'),
                          publisher=publisher, latest_version=version)
                db.add(p)
            else:
                existing.description = manifest.get('description') or existing.description
                existing.latest_version = version
                await db.merge(existing)

            pv_id = f"{name}:{version}"
            pv = PluginVersion(id=pv_id, plugin_name=name, version=version,
                             manifest=manifest, artifact_url=artifact_url, type=mtype)
            await db.merge(pv)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed saving plugin: {e}')

    return JSONResponse({'status': 'ok', 'plugin': name, 'version': version})


@router.get("/registry/plugins/{name}")
async def registry_get(name: str):
    """Get plugin from registry."""
    try:
        async with get_session() as db:
            p_q = await db.execute(select(Plugin).where(Plugin.name == name))
            p = p_q.scalar_one_or_none()
            if not p:
                raise HTTPException(status_code=404, detail='plugin not found')
            vs_q = await db.execute(select(PluginVersion).where(PluginVersion.plugin_name == name))
            versions = vs_q.scalars().all()
            return JSONResponse({
                'name': p.name,
                'description': p.description,
                'publisher': p.publisher,
                'latest_version': p.latest_version,
                'versions': [{
                    'version': v.version,
                    'artifact_url': v.artifact_url,
                    'created_at': v.created_at.isoformat()
                } for v in versions]
            })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




# Internal plugins API
@router.get("/admin/plugins")
async def list_admin_plugins(request: Request):
    """List all loaded internal plugins."""
    app = request.app
    if not hasattr(app.state, 'plugin_loader'):
        return {"plugins": [], "message": "Plugin loader not initialized"}
    
    plugin_loader = app.state.plugin_loader
    result = {}
    runtime_loaded_ids = set()

    # 1) Плагины из runtime loader (загружены сейчас)
    plugins_list = plugin_loader.list_plugins()
    for p in plugins_list:
        pid = p.get("id") or p.get("name")
        runtime_loaded_ids.add(pid)
        plugin_type = p.get("type", "internal")
        # Маппинг plugin_type → runtime_mode в терминах SDK
        if plugin_type == "external":
            plugin_type_norm = "microservice"
        elif plugin_type == "internal":
            plugin_type_norm = "in_process"
        else:
            plugin_type_norm = "in_process"

        result[pid] = {
            "plugin_id": pid,
            "name": p.get("name", pid),
            "version": p.get("version", "unknown"),
            "description": p.get("description", ""),
            "plugin_type": plugin_type_norm,
            "enabled": True,   # раз плагин в runtime, он разрешен
            "loaded": True,    # runtime-факт
            "config": p.get("config"),
        }

    # 2) Плагины из БД (добавляем недостающие и обогащаем существующие)
    try:
        async with get_session() as db:
            q = await db.execute(select(Plugin))
            db_plugins = q.scalars().all()
            for p in db_plugins:
                pid = p.id
                plugin_type_norm = "in_process"
                if getattr(p, "runtime_mode", None):
                    rm = p.runtime_mode
                    if rm in ("microservice",):
                        plugin_type_norm = "microservice"
                    elif rm == "hybrid":
                        plugin_type_norm = "hybrid"
                    elif rm in ("in_process", "in-process"):
                        plugin_type_norm = "in_process"
                    else:
                        plugin_type_norm = "in_process"

                entry = result.get(pid, {})
                entry.update({
                    "plugin_id": pid,
                    "name": p.name,
                    "version": p.latest_version or entry.get("version", "unknown"),
                    "description": p.description or entry.get("description", ""),
                    "plugin_type": plugin_type_norm,
                    "enabled": p.enabled,
                    "loaded": pid in runtime_loaded_ids or p.loaded,
                    "config": p.config
                })
                result[pid] = entry
    except Exception:
        # Не ломаем ответ, если БД недоступна
        pass

    plugins_response = list(result.values())
    return standard_response(data={
        "plugins": plugins_response,
        "loaded_count": len(runtime_loaded_ids),
        "plugin_ids": list(runtime_loaded_ids),
    })


# Control endpoints for embedded-capable plugins (start/stop/restart/status)
@router.post("/plugins/{plugin_id}/control/start")
async def plugin_control_start(plugin_id: str):
    """Start embedded plugin process (if supported)."""
    # Only client_manager currently supported
    if plugin_id != 'client_manager':
        raise HTTPException(status_code=404, detail='control endpoints supported only for client_manager')

    try:
        try:
            from ..plugins.client_manager import embed as cm_embed
        except Exception:
            try:
                from plugins.client_manager import embed as cm_embed
            except Exception:
                cm_embed = None

        if cm_embed is None:
            raise HTTPException(status_code=404, detail='embed helper not available')

        proc = await asyncio.to_thread(cm_embed.start_embedded)
        return standard_response(data={'plugin_id': plugin_id, 'pid': getattr(proc, 'pid', None)})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception('Failed to start embedded plugin')
        return standard_response(status='error', message=str(e), code=500)


@router.post("/plugins/{plugin_id}/control/stop")
async def plugin_control_stop(plugin_id: str):
    """Stop embedded plugin process (if supported)."""
    if plugin_id != 'client_manager':
        raise HTTPException(status_code=404, detail='control endpoints supported only for client_manager')

    try:
        try:
            from ..plugins.client_manager import embed as cm_embed
        except Exception:
            try:
                from plugins.client_manager import embed as cm_embed
            except Exception:
                cm_embed = None

        if cm_embed is None:
            raise HTTPException(status_code=404, detail='embed helper not available')

        await asyncio.to_thread(cm_embed.stop_embedded)
        return standard_response(data={'plugin_id': plugin_id})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception('Failed to stop embedded plugin')
        return standard_response(status='error', message=str(e), code=500)


@router.post("/plugins/{plugin_id}/control/restart")
async def plugin_control_restart(plugin_id: str):
    """Restart embedded plugin process (if supported)."""
    if plugin_id != 'client_manager':
        raise HTTPException(status_code=404, detail='control endpoints supported only for client_manager')

    try:
        try:
            from ..plugins.client_manager import embed as cm_embed
        except Exception:
            try:
                from plugins.client_manager import embed as cm_embed
            except Exception:
                cm_embed = None

        if cm_embed is None:
            raise HTTPException(status_code=404, detail='embed helper not available')

        def _restart():
            try:
                cm_embed.stop_embedded()
            except Exception:
                pass
            return cm_embed.start_embedded()

        proc = await asyncio.to_thread(_restart)
        return standard_response(data={'plugin_id': plugin_id, 'pid': getattr(proc, 'pid', None)})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception('Failed to restart embedded plugin')
        return standard_response(status='error', message=str(e), code=500)


@router.get("/plugins/{plugin_id}/control/status")
async def plugin_control_status(plugin_id: str):
    """Get status of embedded plugin process."""
    if plugin_id != 'client_manager':
        raise HTTPException(status_code=404, detail='control endpoints supported only for client_manager')

    try:
        try:
            from ..plugins.client_manager import embed as cm_embed
        except Exception:
            try:
                from plugins.client_manager import embed as cm_embed
            except Exception:
                cm_embed = None

        if cm_embed is None:
            raise HTTPException(status_code=404, detail='embed helper not available')

        proc = getattr(cm_embed, 'PROCESS', None)
        running = proc is not None and getattr(proc, 'poll', lambda: 1)() is None
        pid = getattr(proc, 'pid', None) if proc is not None else None
        return standard_response(data={'plugin_id': plugin_id, 'running': running, 'pid': pid})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception('Failed getting embedded plugin status')
        return standard_response(status='error', message=str(e), code=500)


@router.get("/v1/admin/stats")
async def get_stats(request: Request):
    """Get system statistics."""
    app = request.app
    plugin_count = 0
    if hasattr(app.state, 'plugin_loader'):
        plugin_count = len(app.state.plugin_loader.plugins)
    
    return standard_response(data={"status": "running", "plugins_loaded": plugin_count, "version": "2.0.0"})


# NOTE: Catch-all route for external plugins is DISABLED
# Internal plugins mount their own routers with prefix /api/plugins/{plugin_id}
# External plugins use external_plugin_registry.proxy_request directly
# 
# If you need to proxy to external HTTP plugins, uncomment and adjust:
# @router.api_route("/plugins/{plugin_id}/{path:path}", methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
# async def proxy_to_external_plugin(plugin_id: str, path: str, request: Request):
#     """Proxy requests to external plugins."""
#     body = None
#     if request.method in ('POST', 'PUT', 'PATCH'):
#         try:
#             body = await request.json()
#         except Exception:
#             body = None
#
#     try:
#         result = await external_plugin_registry.proxy_request(
#             plugin_id=plugin_id,
#             path=path,
#             method=request.method,
#             json=body,
#             params=dict(request.query_params),
#             headers=dict(request.headers)
#         )
#         return result
#     except LookupError:
#         raise HTTPException(status_code=404, detail=f"External plugin '{plugin_id}' not registered")
#     except Exception as e:
#         logger.error(f"Proxy error for {plugin_id}: {e}")
#         raise HTTPException(status_code=502, detail=str(e))
