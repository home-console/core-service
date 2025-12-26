"""
Модуль для управления роутерами плагинов
"""

import logging
import asyncio
from typing import Dict, List, Optional, Any
from fastapi import FastAPI

logger = logging.getLogger(__name__)


class PluginRouterManager:
    """Менеджер роутеров плагинов"""
    
    def __init__(self, app: FastAPI, lock: Optional[asyncio.Lock] = None):
        """
        Инициализация менеджера роутеров.
        
        Args:
            app: FastAPI приложение
            lock: Async lock для потокобезопасности
        """
        self.app = app
        self._lock = lock or asyncio.Lock()
        # Словарь для отслеживания роутеров плагинов
        # Ключ: plugin_id, Значение: список route объектов
        self.plugin_routes: Dict[str, List] = {}
    
    async def mount_router(
        self,
        plugin_id: str,
        plugin_name: str,
        router,
        metadata: Dict[str, Any]
    ) -> bool:
        """
        Монтировать роутер плагина в приложение.
        
        Args:
            plugin_id: ID плагина
            plugin_name: Имя плагина
            router: FastAPI Router объект
            metadata: Метаданные плагина
            
        Returns:
            True если успешно, False иначе
        """
        if not router:
            logger.debug(f"  ℹ️ Plugin {plugin_id} has no router to mount")
            return False
        
        try:
            # Определяем prefix: инфраструктурные плагины без префикса
            is_infrastructure = (
                metadata.get('infrastructure', False) or
                metadata.get('type') == 'infrastructure'
            )
            
            if is_infrastructure:
                prefix = "/api"
                logger.debug(f"  🏗️ Infrastructure plugin {plugin_id} mounted at {prefix}")
            else:
                prefix = f"/api/plugins/{plugin_id}"
            
            # Сохраняем состояние роутеров до монтирования
            before_app_routes = list(self.app.routes)
            before_router_routes = None
            if hasattr(self.app, 'router') and hasattr(self.app.router, 'routes'):
                try:
                    before_router_routes = list(self.app.router.routes)
                except Exception as e:
                    logger.debug(f"Could not get router routes: {e}")
            
            # Монтируем router
            self.app.include_router(
                router,
                prefix=prefix,
                tags=[plugin_name]
            )
            logger.info(f"✅ Router mounted at {prefix}")
            
            # Сохраняем добавленные routes для удаления
            added_routes = []
            try:
                after_app_routes = list(self.app.routes)
                for r in after_app_routes:
                    if r not in before_app_routes:
                        added_routes.append(r)
            except Exception as e:
                logger.debug(f"Could not track app routes: {e}")
            
            try:
                if before_router_routes is not None and hasattr(self.app, 'router'):
                    after_router_routes = list(self.app.router.routes)
                    for r in after_router_routes:
                        if r not in before_router_routes and r not in added_routes:
                            added_routes.append(r)
            except Exception as e:
                logger.debug(f"Could not track router routes: {e}")
            
            # Сохраняем route objects
            try:
                async with self._lock:
                    self.plugin_routes[plugin_id] = added_routes
            except Exception:
                self.plugin_routes[plugin_id] = added_routes
            
            # Force regenerate OpenAPI schema
            try:
                if hasattr(self.app, 'openapi_schema'):
                    self.app.openapi_schema = None
            except Exception:
                pass
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to mount router for {plugin_id}: {e}", exc_info=True)
            return False
    
    async def unmount_router(self, plugin_id: str) -> int:
        """
        Размонтировать роутер плагина.
        
        Args:
            plugin_id: ID плагина
            
        Returns:
            Количество удаленных роутеров
        """
        removed_count = 0
        saved = self.plugin_routes.get(plugin_id)
        
        if isinstance(saved, list):
            routes_to_remove = list(saved)
            for route in routes_to_remove:
                try:
                    if route in getattr(self.app, 'routes', []):
                        self.app.routes.remove(route)
                        removed_count += 1
                        logger.debug(f"  ✅ Removed route from app.routes: {getattr(route, 'path', 'unknown')}")
                    elif hasattr(self.app, 'router') and hasattr(self.app.router, 'routes') and route in self.app.router.routes:
                        self.app.router.routes.remove(route)
                        removed_count += 1
                        logger.debug(f"  ✅ Removed route from router.routes: {getattr(route, 'path', 'unknown')}")
                except Exception as e:
                    logger.debug(f"  ⚠️ Could not remove saved route {getattr(route, 'path', 'unknown')}: {e}")
            
            # Очищаем сохраненные данные
            try:
                async with self._lock:
                    if plugin_id in self.plugin_routes:
                        del self.plugin_routes[plugin_id]
            except Exception:
                if plugin_id in self.plugin_routes:
                    del self.plugin_routes[plugin_id]
            
            if removed_count == 0:
                logger.warning(f"⚠️ No saved routes removed for plugin {plugin_id}")
            else:
                logger.info(f"🗑️ Removed {removed_count} saved route(s) for plugin {plugin_id}")
            
            # Обновляем OpenAPI схему
            if hasattr(self.app, 'openapi_schema'):
                self.app.openapi_schema = None
                logger.debug(f"  🔄 Cleared OpenAPI schema cache for Swagger update")
        
        return removed_count

