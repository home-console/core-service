"""
Device management routes - Core functionality.
Handles device CRUD operations, bindings, and intent mappings.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from pydantic import BaseModel

try:
    from ..db import get_session
    from ..models import Device, PluginBinding, IntentMapping
except ImportError:
    from db import get_session
    from models import Device, PluginBinding, IntentMapping

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


class IntentMappingCreate(BaseModel):
    intent_name: str
    selector: Optional[str] = None
    plugin_action: str
    payload_template: Optional[str] = None


# ============= Device Routes =============

@router.get("/devices")
async def list_devices() -> JSONResponse:
    """Get list of all devices."""
    async with get_session() as db:
        result = await db.execute(select(Device))
        devices = result.scalars().all()
        return JSONResponse([
            {
                "id": d.id,
                "name": d.name,
                "type": d.type,
                "meta": d.meta,
                "created_at": d.created_at.isoformat() if d.created_at else None
            }
            for d in devices
        ])


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
            "created_at": device.created_at.isoformat() if device.created_at else None
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
            meta=device_data.meta
        )
        db.add(device)
        await db.flush()
        
        return JSONResponse({
            "id": device.id,
            "name": device.name,
            "type": device.type,
            "meta": device.meta,
            "created_at": device.created_at.isoformat() if device.created_at else None
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


@router.post("/devices/{device_id}/execute")
async def execute_device_action(device_id: str, payload: Dict[str, Any]) -> JSONResponse:
    """
    Execute action on device.
    
    This endpoint finds the appropriate plugin binding and forwards the action.
    """
    async with get_session() as db:
        # Проверяем существование устройства
        device_result = await db.execute(select(Device).where(Device.id == device_id))
        device = device_result.scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=404, detail=f"Device '{device_id}' not found")
        
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
                detail=f"No active plugin bindings found for device '{device_id}'"
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
        await event_bus.emit(f"device.{device_id}.{action}", {
            "device_id": device_id,
            "plugin": binding.plugin_name,
            "config": binding.config,
            "payload": payload
        })
        
        return JSONResponse({
            "status": "ok",
            "message": f"Action '{action}' forwarded to plugin '{binding.plugin_name}'",
            "device_id": device_id
        })


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

