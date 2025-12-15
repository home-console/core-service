"""
Пример встраиваемого плагина devices.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from home_console_sdk.plugin import InternalPluginBase


class DeviceSchema(BaseModel):
    id: Optional[str] = None
    name: str
    type: str
    state: Optional[dict] = None


class DevicesPlugin(InternalPluginBase):
    """Встраиваемый плагин управления устройствами."""
    
    id = "devices"
    name = "Devices Manager"
    version = "1.0.0"
    description = "Internal device management plugin"
    
    async def on_load(self):
        """Инициализация при загрузке плагина."""
        self.router = APIRouter()
        
        # Регистрируем endpoints
        self.router.add_api_route(
            "/list",
            self.list_devices,
            methods=["GET"],
            response_model=List[DeviceSchema]
        )
        self.router.add_api_route(
            "/create",
            self.create_device,
            methods=["POST"],
            response_model=DeviceSchema
        )
        
        # Подписываемся на события
        await self.subscribe_event("*.device.*", self.on_device_event)
        
        self.logger.info("✅ Devices plugin loaded")
    
    async def on_unload(self):
        """Cleanup при выгрузке плагина."""
        self.logger.info("👋 Devices plugin unloaded")
    
    async def list_devices(self) -> List[DeviceSchema]:
        """Получить список устройств."""
        # Пример: в production используй self.db_session_maker() для доступа к БД
        self.logger.debug("Listing devices")
        return [
            DeviceSchema(id="dev_1", name="Living Room Light", type="light", state={"power": "on"}),
            DeviceSchema(id="dev_2", name="Bedroom Sensor", type="sensor", state={"temperature": 22.5}),
        ]
    
    async def create_device(self, device: DeviceSchema) -> DeviceSchema:
        """Создать устройство."""
        device.id = f"dev_{id(device)}"
        
        self.logger.info(f"Device created: {device.name}")
        
        # Отправляем событие
        await self.emit_event("device_created", {
            "device_id": device.id,
            "name": device.name,
            "type": device.type
        })
        
        return device
    
    async def on_device_event(self, event_name: str, data: dict):
        """Обработчик событий от других плагинов."""
        self.logger.info(f"📢 Device event: {event_name}, data: {data}")
