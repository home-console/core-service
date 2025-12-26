"""
Device management routes - Core functionality.
Handles device CRUD operations, bindings, and intent mappings.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
import logging

from fastapi import APIRouter, HTTPException, Request, Depends, BackgroundTasks, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from pydantic import BaseModel

from ..db import get_session
from ..models import Device, PluginBinding, IntentMapping, DeviceLink, User
from ..routes.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


# ============= Pydantic Schemas =============

class DeviceCreate(BaseModel):
    name: str
    type: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None


class DeviceResponse(BaseModel):
    id: str
    name: str
    type: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PluginBindingCreate(BaseModel):
    device_id: str
    plugin_name: str
    config: Optional[Dict[str, Any]] = None
    enabled: bool = True


class DeviceLinkCreate(BaseModel):
    source_device_id: str  # Устройство-источник (например, из Яндекса)
    target_device_id: str  # Устройство-цель (например, локальное)
    link_type: Optional[str] = "bridge"  # Тип связи: 'bridge', 'proxy', 'sync', 'mirror'
    direction: str = "bidirectional"  # 'unidirectional' или 'bidirectional'
    config: Optional[Dict[str, Any]] = None
    enabled: bool = True


class IntentMappingCreate(BaseModel):
    intent_name: str
    selector: Optional[str] = None
    plugin_action: str
    payload_template: Optional[str] = None


# ============= Device Routes =============

@router.get("/devices")
async def list_devices() -> JSONResponse:
    """Get list of all devices with bindings and states."""
    async with get_session() as db:
        result = await db.execute(select(Device))
        devices = result.scalars().all()
        
        devices_list = []
        for d in devices:
            # Получаем привязки для устройства
            bindings_result = await db.execute(
                select(PluginBinding).where(PluginBinding.device_id == d.id)
            )
            bindings = bindings_result.scalars().all()
            
            # Извлекаем информацию о состоянии из meta
            state = None
            if d.meta and isinstance(d.meta, dict):
                state = d.meta.get('state') or d.meta.get('yandex_device', {}).get('state')
            
            devices_list.append({
                "id": d.id,
                "name": d.name,
                "type": d.type,
                "meta": d.meta,
                "state": state,
                "is_online": d.is_online,
                "is_on": d.is_on,
                "last_seen": d.last_seen.isoformat() if d.last_seen else None,
                "bindings": [
                    {
                        "id": b.id,
                        "plugin_name": b.plugin_name,
                        "selector": b.selector,
                        "enabled": b.enabled,
                        "config": b.config
                    }
                    for b in bindings
                ],
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None
            })
        
        return JSONResponse(devices_list)


@router.get("/devices/{device_id}")
async def get_device(device_id: str) -> JSONResponse:
    """Get device by ID."""
    async with get_session() as db:
        result = await db.execute(select(Device).where(Device.id == device_id))
        device = result.scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=404, detail=f"Device '{device_id}' not found")
        
        return JSONResponse({
            "id": device.id,
            "name": device.name,
            "type": device.type,
            "meta": device.meta,
            "is_online": device.is_online,
            "is_on": device.is_on,
            "last_seen": device.last_seen.isoformat() if device.last_seen else None,
            "created_at": device.created_at.isoformat() if device.created_at else None,
            "updated_at": device.updated_at.isoformat() if device.updated_at else None
        })


@router.post("/devices")
async def create_device(device_data: DeviceCreate) -> JSONResponse:
    """Create a new device."""
    import uuid
    device_id = f"dev_{uuid.uuid4().hex[:16]}"
    
    async with get_session() as db:
        device = Device(
            id=device_id,
            name=device_data.name,
            type=device_data.type,
            meta=device_data.meta,
            is_online=False,
            is_on=False
        )
        db.add(device)
        await db.flush()
        
        return JSONResponse({
            "id": device.id,
            "name": device.name,
            "type": device.type,
            "meta": device.meta,
            "is_online": device.is_online,
            "is_on": device.is_on,
            "last_seen": device.last_seen.isoformat() if device.last_seen else None,
            "created_at": device.created_at.isoformat() if device.created_at else None,
            "updated_at": device.updated_at.isoformat() if device.updated_at else None
        }, status_code=201)


@router.put("/devices/{device_id}")
async def update_device(device_id: str, device_data: DeviceUpdate) -> JSONResponse:
    """Update device."""
    async with get_session() as db:
        result = await db.execute(select(Device).where(Device.id == device_id))
        device = result.scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=404, detail=f"Device '{device_id}' not found")
        
        if device_data.name is not None:
            device.name = device_data.name
        if device_data.type is not None:
            device.type = device_data.type
        if device_data.meta is not None:
            device.meta = device_data.meta
        
        await db.merge(device)
        
        return JSONResponse({
            "id": device.id,
            "name": device.name,
            "type": device.type,
            "meta": device.meta,
            "created_at": device.created_at.isoformat() if device.created_at else None
        })


@router.delete("/devices/{device_id}")
async def delete_device(device_id: str) -> JSONResponse:
    """Delete device."""
    async with get_session() as db:
        result = await db.execute(select(Device).where(Device.id == device_id))
        device = result.scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=404, detail=f"Device '{device_id}' not found")
        
        # Проверяем наличие привязок
        bindings_result = await db.execute(
            select(PluginBinding).where(PluginBinding.device_id == device_id)
        )
        bindings = bindings_result.scalars().all()
        if bindings:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete device '{device_id}': {len(bindings)} plugin bindings exist"
            )
        
        await db.delete(device)
        
        return JSONResponse({"status": "ok", "message": f"Device '{device_id}' deleted"})


async def _execute_device_action_internal(device_id: str, payload: Dict[str, Any], link_depth: int = 0) -> Dict[str, Any]:
    """
    Внутренняя функция для выполнения действия на устройстве с поддержкой связей.
    """
    async with get_session() as db:
        # Проверяем существование устройства
        device_result = await db.execute(select(Device).where(Device.id == device_id))
        device = device_result.scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=404, detail=f"Device '{device_id}' not found")
        
        # Проверяем наличие активных связей, где это устройство является источником
        links_result = await db.execute(
            select(DeviceLink).where(
                DeviceLink.source_device_id == device_id,
                DeviceLink.enabled == True
            )
        )
        active_links = links_result.scalars().all()
        
        # Если есть активные связи, перенаправляем команду на связанное устройство
        if active_links and link_depth < 5:  # Ограничение глубины для предотвращения циклов
            # Используем первую активную связь
            link = active_links[0]
            target_device_id = link.target_device_id
            
            # Добавляем информацию о перенаправлении в payload
            redirected_payload = {
                **payload,
                "_original_device_id": device_id,
                "_link_id": link.id,
                "_link_type": link.link_type
            }
            
            # Рекурсивно вызываем для связанного устройства
            return await _execute_device_action_internal(target_device_id, redirected_payload, link_depth + 1)
        
        if link_depth >= 5:
            raise HTTPException(
                status_code=400,
                detail="Maximum link depth exceeded (possible circular link)"
            )
        
        # Если связей нет, используем стандартную логику с плагинами
        # Находим активные привязки плагинов
        bindings_result = await db.execute(
            select(PluginBinding).where(
                PluginBinding.device_id == device_id,
                PluginBinding.enabled == True
            )
        )
        bindings = bindings_result.scalars().all()
        
        if not bindings:
            raise HTTPException(
                status_code=400,
                detail=f"No active plugin bindings or device links found for device '{device_id}'"
            )
        
        # Пока используем первую активную привязку
        # В будущем можно добавить логику выбора по типу действия
        binding = bindings[0]
        
        # Публикуем событие для плагина
        # Плагины должны подписаться на события типа "device.{device_id}.execute"
        try:
            from ..event_bus import event_bus
        except ImportError:
            from event_bus import event_bus
        
        action = payload.get("action", "execute")
        event_name = f"device.{device_id}.{action}"
        event_data = {
            "device_id": device_id,
            "plugin": binding.plugin_name,
            "config": binding.config,
            "payload": payload
        }
        logger.info(f"🔔 PUBLISHING EVENT: {event_name}")
        logger.info(f"🔔 EVENT DATA: {event_data}")
        await event_bus.emit(event_name, event_data)
        
        return {
            "status": "ok",
            "message": f"Action '{action}' forwarded to plugin '{binding.plugin_name}'",
            "device_id": device_id
        }


@router.post("/devices/{device_id}/execute")
async def execute_device_action(device_id: str, payload: Dict[str, Any], request: Request) -> JSONResponse:
    """
    Execute action on device.
    
    Этот endpoint:
    1. Проверяет наличие связей устройства (DeviceLink)
    2. Если есть активная связь, перенаправляет команду на связанное устройство
    3. Иначе находит привязку плагина и отправляет команду через плагин
    
    Пример использования связей:
    - Устройство из Яндекса (лампа) -> Локальное устройство (реле)
    - При команде на Яндекс-устройство, команда автоматически перенаправляется на связанное устройство
    """
    # Получаем user_id из токена
    user_id = None
    try:
        from ..routes.auth import verify_token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            payload_data = verify_token(token)
            if payload_data:
                user_id = payload_data.get("sub")
        elif request.cookies.get("access_token"):
            token = request.cookies.get("access_token")
            payload_data = verify_token(token)
            if payload_data:
                user_id = payload_data.get("sub")
    except Exception as e:
        # Если не удалось получить user_id, продолжаем без него
        pass
    
    # Добавляем user_id в payload для плагина
    if user_id:
        payload['user_id'] = user_id
    
    result = await _execute_device_action_internal(device_id, payload)
    return JSONResponse(result)


# ============= Yandex Sync Routes =============

@router.post("/devices/yandex/sync-all")
async def sync_all_yandex_devices(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    full_sync: bool = Query(False, description="Полная синхронизация (медленнее, но обновляет все данные устройств)")
) -> JSONResponse:
    """
    Синхронизировать все устройства Яндекса в один запрос.
    Вызывает GET /v1.0/user/info один раз и обновляет состояние всех устройств.
    Также получает полные данные каждого устройства через GET /v1.0/devices/{device_id}.
    """
    user_id = current_user.id
    logger.info(f"Syncing Yandex devices for user: {user_id}")
    
    # Получаем плагин Яндекса
    try:
        app = request.app
        if hasattr(app.state, 'plugin_loader'):
            plugin_loader = app.state.plugin_loader
            yandex_plugin = plugin_loader.plugins.get('yandex_smart_home')
            
            if yandex_plugin:
                sync_stats = {
                    'step1_synced_new': 0,
                    'step1_updated': 0,
                    'step1_total': 0,
                    'step2_updated': 0,
                    'step3_updated': 0,
                    'errors': []
                }
                
                # Шаг 1: Синхронизируем список устройств
                logger.info(f"Step 1: Syncing device list for user {user_id}")
                try:
                    step1_result = await yandex_plugin.sync_devices({'user_id': user_id})
                    if hasattr(step1_result, 'body'):
                        import json
                        step1_data = json.loads(step1_result.body.decode('utf-8'))
                        sync_stats['step1_synced_new'] = step1_data.get('synced_new_devices', 0)
                        sync_stats['step1_updated'] = step1_data.get('updated_devices', 0)
                        sync_stats['step1_total'] = step1_data.get('total_yandex_devices', 0)
                    logger.info(f"Step 1 completed: {sync_stats['step1_synced_new']} new, {sync_stats['step1_updated']} updated, {sync_stats['step1_total']} total")
                except Exception as e:
                    error_msg = f"Step 1 failed: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    sync_stats['errors'].append(error_msg)
                
                # Шаг 2: Синхронизируем состояния устройств
                logger.info(f"Step 2: Syncing device states for user {user_id}")
                try:
                    step2_result = await yandex_plugin.sync_device_states({'user_id': user_id})
                    if hasattr(step2_result, 'body'):
                        import json
                        step2_data = json.loads(step2_result.body.decode('utf-8'))
                        sync_stats['step2_updated'] = step2_data.get('updated_states', 0)
                    logger.info(f"Step 2 completed: {sync_stats['step2_updated']} states updated")
                except Exception as e:
                    error_msg = f"Step 2 failed: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    sync_stats['errors'].append(error_msg)
                
                # Шаг 3: Получаем полные данные каждого устройства (capabilities, properties, last_updated)
                # Опционально - можно пропустить для быстрой синхронизации
                if full_sync:
                    logger.info(f"Step 3: Polling authoritative states for user {user_id}")
                    try:
                        if hasattr(yandex_plugin, 'device_manager') and yandex_plugin.device_manager:
                            # Запускаем в фоне, чтобы не блокировать ответ
                            async def poll_states_task():
                                try:
                                    updated = await yandex_plugin.device_manager.poll_authoritative_states(
                                        user_id=user_id,
                                        concurrency=20,  # Увеличиваем параллелизм
                                        delay_between=0.01  # Уменьшаем задержку
                                    )
                                    logger.info(f"Step 3 (background) completed: {updated} devices updated with full data")
                                except Exception as e:
                                    logger.error(f"Step 3 (background) failed: {e}", exc_info=True)
                            
                            background_tasks.add_task(poll_states_task)
                            sync_stats['step3_updated'] = -1  # -1 означает "в процессе в фоне"
                            logger.info(f"Step 3 started in background (full sync enabled)")
                        else:
                            logger.warning("Device manager not available, skipping step 3")
                    except Exception as e:
                        error_msg = f"Step 3 failed: {str(e)}"
                        logger.error(error_msg, exc_info=True)
                        sync_stats['errors'].append(error_msg)
                else:
                    logger.info(f"Step 3 skipped (full_sync=false for faster response)")
                    sync_stats['step3_updated'] = 0
                
                # Возвращаем обновленный список устройств
                async with get_session() as db:
                    result = await db.execute(select(Device))
                    devices = result.scalars().all()
                    
                    devices_list = []
                    for d in devices:
                        # Получаем привязки для устройства
                        bindings_result = await db.execute(
                            select(PluginBinding).where(PluginBinding.device_id == d.id)
                        )
                        bindings = bindings_result.scalars().all()
                        
                        # Проверяем, что это устройство Яндекса
                        has_yandex_binding = any(b.plugin_name == 'yandex_smart_home' for b in bindings)
                        if has_yandex_binding:
                            devices_list.append({
                                "id": d.id,
                                "name": d.name,
                                "type": d.type,
                                "meta": d.meta,
                                "is_online": d.is_online,
                                "is_on": d.is_on,
                                "last_seen": d.last_seen.isoformat() if d.last_seen else None,
                                "bindings": [
                                    {
                                        "id": b.id,
                                        "plugin_name": b.plugin_name,
                                        "selector": b.selector,
                                        "enabled": b.enabled,
                                        "config": b.config
                                    }
                                    for b in bindings
                                ],
                                "updated_at": d.updated_at.isoformat() if d.updated_at else None
                            })
                    
                    return JSONResponse({
                        "status": "ok" if not sync_stats['errors'] else "partial",
                        "message": f"Synced {len(devices_list)} Yandex devices",
                        "stats": {
                            "step1": {
                                "synced_new": sync_stats['step1_synced_new'],
                                "updated": sync_stats['step1_updated'],
                                "total": sync_stats['step1_total']
                            },
                            "step2": {
                                "updated_states": sync_stats['step2_updated']
                            },
                            "step3": {
                                "updated_full_data": sync_stats['step3_updated']
                            },
                            "errors": sync_stats['errors'] if sync_stats['errors'] else None
                        },
                        "devices": devices_list
                    })
            else:
                raise HTTPException(status_code=500, detail="Yandex Smart Home plugin not loaded")
        else:
            raise HTTPException(status_code=500, detail="Plugin loader not available")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error syncing Yandex devices: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error syncing devices: {str(e)}")


@router.post("/devices/yandex/sync/{device_id}")
async def sync_single_yandex_device(
    device_id: str,
    request: Request,
    current_user: User = Depends(get_current_user)
) -> JSONResponse:
    """
    Синхронизировать одно конкретное устройство Яндекса.
    Получает полные данные устройства через GET /v1.0/devices/{yandex_device_id}.
    """
    user_id = current_user.id
    logger.info(f"Syncing single Yandex device {device_id} for user: {user_id}")
    
    try:
        app = request.app
        if not hasattr(app.state, 'plugin_loader'):
            raise HTTPException(status_code=500, detail="Plugin loader not available")
        
        plugin_loader = app.state.plugin_loader
        yandex_plugin = plugin_loader.plugins.get('yandex_smart_home')
        
        if not yandex_plugin:
            raise HTTPException(status_code=500, detail="Yandex Smart Home plugin not loaded")
        
        # Находим устройство и его привязку к Яндексу
        async with get_session() as db:
            device_result = await db.execute(
                select(Device).where(Device.id == device_id)
            )
            device = device_result.scalar_one_or_none()
            
            if not device:
                raise HTTPException(status_code=404, detail=f"Device {device_id} not found")
            
            # Находим привязку к Яндексу
            binding_result = await db.execute(
                select(PluginBinding).where(
                    PluginBinding.device_id == device_id,
                    PluginBinding.plugin_name == 'yandex_smart_home'
                )
            )
            binding = binding_result.scalar_one_or_none()
            
            if not binding or not binding.selector:
                raise HTTPException(status_code=404, detail=f"Device {device_id} is not a Yandex device")
            
            yandex_device_id = binding.selector
            
            # Получаем access token
            from core_service.plugins.yandex_smart_home.models import YandexUser
            account_result = await db.execute(
                select(YandexUser).where(YandexUser.user_id == user_id)
            )
            account = account_result.scalar_one_or_none()
            
            if not account or not account.access_token:
                raise HTTPException(status_code=401, detail="Yandex account not linked or token expired")
            
            # Получаем полные данные устройства из Яндекса
            if hasattr(yandex_plugin, 'api_client') and yandex_plugin.api_client:
                device_data = await yandex_plugin.api_client.get_device(
                    account.access_token,
                    yandex_device_id
                )
                
                if not device_data:
                    raise HTTPException(status_code=404, detail=f"Yandex device {yandex_device_id} not found")
                
                # Обновляем состояние устройства
                if hasattr(yandex_plugin, 'state_manager') and yandex_plugin.state_manager:
                    await yandex_plugin.state_manager.update_device_status(device_id, device_data)
                
                # Обновляем метаданные устройства
                if not device.meta:
                    device.meta = {}
                device.meta['yandex_device'] = device_data
                device.meta['yandex_device_id'] = yandex_device_id
                device.meta['last_sync'] = datetime.utcnow().isoformat()
                
                # Обновляем конфигурацию привязки
                if not binding.config:
                    binding.config = {}
                binding.config['yandex_device'] = device_data
                binding.config['last_sync'] = datetime.utcnow().isoformat()
                
                await db.commit()
                
                return JSONResponse({
                    "status": "ok",
                    "message": f"Device {device_id} synced successfully",
                    "device": {
                        "id": device.id,
                        "name": device.name,
                        "type": device.type,
                        "is_online": device.is_online,
                        "is_on": device.is_on,
                        "last_seen": device.last_seen.isoformat() if device.last_seen else None
                    }
                })
            else:
                raise HTTPException(status_code=500, detail="API client not available")
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error syncing device {device_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error syncing device: {str(e)}")


# ============= Plugin Binding Routes =============

@router.get("/devices/{device_id}/bindings")
async def list_device_bindings(device_id: str) -> JSONResponse:
    """Get plugin bindings for device."""
    async with get_session() as db:
        result = await db.execute(
            select(PluginBinding).where(PluginBinding.device_id == device_id)
        )
        bindings = result.scalars().all()
        
        return JSONResponse([
            {
                "id": b.id,
                "device_id": b.device_id,
                "plugin_name": b.plugin_name,
                "config": b.config,
                "enabled": b.enabled,
                "created_at": b.created_at.isoformat() if b.created_at else None
            }
            for b in bindings
        ])


@router.post("/devices/{device_id}/bindings")
async def create_device_binding(device_id: str, binding_data: PluginBindingCreate) -> JSONResponse:
    """Create plugin binding for device."""
    async with get_session() as db:
        # Проверяем существование устройства
        device_result = await db.execute(select(Device).where(Device.id == device_id))
        device = device_result.scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=404, detail=f"Device '{device_id}' not found")
        
        import uuid
        binding_id = f"bind_{uuid.uuid4().hex[:16]}"
        
        binding = PluginBinding(
            id=binding_id,
            device_id=device_id,
            plugin_name=binding_data.plugin_name,
            config=binding_data.config,
            enabled=binding_data.enabled
        )
        db.add(binding)
        await db.flush()
        
        return JSONResponse({
            "id": binding.id,
            "device_id": binding.device_id,
            "plugin_name": binding.plugin_name,
            "config": binding.config,
            "enabled": binding.enabled,
            "created_at": binding.created_at.isoformat() if binding.created_at else None
        }, status_code=201)


@router.delete("/devices/{device_id}/bindings/{binding_id}")
async def delete_device_binding(device_id: str, binding_id: str) -> JSONResponse:
    """Delete plugin binding."""
    async with get_session() as db:
        result = await db.execute(
            select(PluginBinding).where(
                PluginBinding.id == binding_id,
                PluginBinding.device_id == device_id
            )
        )
        binding = result.scalar_one_or_none()
        if not binding:
            raise HTTPException(status_code=404, detail=f"Binding '{binding_id}' not found")
        
        await db.delete(binding)
        
        return JSONResponse({"status": "ok", "message": f"Binding '{binding_id}' deleted"})


# ============= Intent Mapping Routes =============

@router.get("/intents")
async def list_intents() -> JSONResponse:
    """Get list of intent mappings."""
    async with get_session() as db:
        result = await db.execute(select(IntentMapping))
        intents = result.scalars().all()
        
        return JSONResponse([
            {
                "id": i.id,
                "intent_name": i.intent_name,
                "selector": i.selector,
                "plugin_action": i.plugin_action,
                "payload_template": i.payload_template,
                "created_at": i.created_at.isoformat() if i.created_at else None
            }
            for i in intents
        ])


@router.post("/intents")
async def create_intent(intent_data: IntentMappingCreate) -> JSONResponse:
    """Create intent mapping."""
    import uuid
    intent_id = f"intent_{uuid.uuid4().hex[:16]}"
    
    async with get_session() as db:
        intent = IntentMapping(
            id=intent_id,
            intent_name=intent_data.intent_name,
            selector=intent_data.selector,
            plugin_action=intent_data.plugin_action,
            payload_template=intent_data.payload_template
        )
        db.add(intent)
        await db.flush()
        
        return JSONResponse({
            "id": intent.id,
            "intent_name": intent.intent_name,
            "selector": intent.selector,
            "plugin_action": intent.plugin_action,
            "payload_template": intent.payload_template,
            "created_at": intent.created_at.isoformat() if intent.created_at else None
        }, status_code=201)


# ============= Device Links Routes =============
# Связи между устройствами (например, Яндекс-устройство -> Локальное устройство)

@router.get("/devices/{device_id}/links")
async def list_device_links(device_id: str) -> JSONResponse:
    """Получить все связи для устройства (как источник, так и цель)."""
    async with get_session() as db:
        # Связи, где устройство является источником
        source_links_result = await db.execute(
            select(DeviceLink).where(DeviceLink.source_device_id == device_id)
        )
        source_links = source_links_result.scalars().all()
        
        # Связи, где устройство является целью
        target_links_result = await db.execute(
            select(DeviceLink).where(DeviceLink.target_device_id == device_id)
        )
        target_links = target_links_result.scalars().all()
        
        # Получаем информацию об устройствах
        def format_link(link: DeviceLink, is_source: bool):
            return {
                "id": link.id,
                "source_device_id": link.source_device_id,
                "target_device_id": link.target_device_id,
                "link_type": link.link_type,
                "direction": link.direction,
                "enabled": link.enabled,
                "config": link.config,
                "created_at": link.created_at.isoformat() if link.created_at else None,
                "role": "source" if is_source else "target"
            }
        
        links = [format_link(link, True) for link in source_links]
        links.extend([format_link(link, False) for link in target_links])
        
        return JSONResponse(links)


@router.post("/devices/links")
async def create_device_link(link_data: DeviceLinkCreate) -> JSONResponse:
    """Создать связь между двумя устройствами."""
    import uuid
    
    async with get_session() as db:
        # Проверяем существование обоих устройств
        source_result = await db.execute(
            select(Device).where(Device.id == link_data.source_device_id)
        )
        source_device = source_result.scalar_one_or_none()
        if not source_device:
            raise HTTPException(
                status_code=404, 
                detail=f"Source device '{link_data.source_device_id}' not found"
            )
        
        target_result = await db.execute(
            select(Device).where(Device.id == link_data.target_device_id)
        )
        target_device = target_result.scalar_one_or_none()
        if not target_device:
            raise HTTPException(
                status_code=404, 
                detail=f"Target device '{link_data.target_device_id}' not found"
            )
        
        # Проверяем, нет ли уже такой связи
        existing_result = await db.execute(
            select(DeviceLink).where(
                DeviceLink.source_device_id == link_data.source_device_id,
                DeviceLink.target_device_id == link_data.target_device_id
            )
        )
        existing = existing_result.scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=400,
                detail="Link between these devices already exists"
            )
        
        link_id = f"link_{uuid.uuid4().hex[:16]}"
        link = DeviceLink(
            id=link_id,
            source_device_id=link_data.source_device_id,
            target_device_id=link_data.target_device_id,
            link_type=link_data.link_type,
            direction=link_data.direction,
            enabled=link_data.enabled,
            config=link_data.config
        )
        db.add(link)
        await db.flush()
        
        return JSONResponse({
            "id": link.id,
            "source_device_id": link.source_device_id,
            "target_device_id": link.target_device_id,
            "link_type": link.link_type,
            "direction": link.direction,
            "enabled": link.enabled,
            "config": link.config,
            "created_at": link.created_at.isoformat() if link.created_at else None
        }, status_code=201)


@router.delete("/devices/links/{link_id}")
async def delete_device_link(link_id: str) -> JSONResponse:
    """Удалить связь между устройствами."""
    async with get_session() as db:
        result = await db.execute(
            select(DeviceLink).where(DeviceLink.id == link_id)
        )
        link = result.scalar_one_or_none()
        if not link:
            raise HTTPException(status_code=404, detail=f"Link '{link_id}' not found")
        
        await db.delete(link)
        await db.commit()
        
        return JSONResponse({"status": "ok", "message": f"Link '{link_id}' deleted"})

