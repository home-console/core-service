"""
Dependency Injection для core-service.

Предоставляет Depends функции для получения зависимостей вместо использования app.state.
"""
from typing import Optional
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .plugin_system.loader import PluginLoader
from .event_bus import EventBus
from .db import get_session, AsyncSession
from .routes.auth import get_current_user

logger = __import__('logging').getLogger(__name__)


def get_plugin_loader(request: Request) -> PluginLoader:
    """
    Dependency для получения PluginLoader.
    
    Использование:
        @router.get("/plugins")
        async def list_plugins(plugin_loader: PluginLoader = Depends(get_plugin_loader)):
            return plugin_loader.list_plugins()
    """
    if not hasattr(request.app.state, 'plugin_loader'):
        logger.error("Plugin loader not available in app.state")
        raise HTTPException(
            status_code=503,
            detail="Plugin loader not initialized. Please wait for application startup."
        )
    return request.app.state.plugin_loader


def get_event_bus(request: Request) -> EventBus:
    """
    Dependency для получения EventBus.
    
    Использование:
        @router.post("/events")
        async def emit_event(
            event_name: str,
            data: dict,
            event_bus: EventBus = Depends(get_event_bus)
        ):
            await event_bus.emit(event_name, data)
    """
    if not hasattr(request.app.state, 'event_bus'):
        logger.error("Event bus not available in app.state")
        raise HTTPException(
            status_code=503,
            detail="Event bus not initialized. Please wait for application startup."
        )
    return request.app.state.event_bus


from contextlib import asynccontextmanager

@asynccontextmanager
async def get_db_session() -> AsyncSession:
    """
    Dependency для получения DB session.
    
    Использование:
        @router.get("/devices")
        async def list_devices(db: AsyncSession = Depends(get_db_session)):
            result = await db.execute(select(Device))
            return result.scalars().all()
    """
    # Используем get_session как async context manager
    async with get_session() as session:
        yield session


# Re-export get_current_user для удобства
__all__ = [
    'get_plugin_loader',
    'get_event_bus',
    'get_db_session',
    'get_current_user',
]

