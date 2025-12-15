"""
PluginLoader: автоматическая загрузка плагинов из папки plugins/.
"""

import importlib
import pkgutil
import logging
from typing import Dict, List, Optional
from .plugin_base import InternalPluginBase
from .event_bus import event_bus

logger = logging.getLogger(__name__)


class PluginLoader:
    """
    Загрузчик внутренних плагинов.
    
    Автоматически находит и загружает все плагины (наследники InternalPluginBase) из папки plugins/.
    Каждый плагин должен быть модулем, содержащим класс, наследующий PluginBase.
    
    Пример использования:
    
    ```python
    # В main.py
    plugin_loader = PluginLoader(app, async_session_maker)
    await plugin_loader.load_all()
    
    # Список плагинов
    plugins = plugin_loader.list_plugins()
    
    # Получить плагин
    device_plugin = plugin_loader.get_plugin("devices")
    ```
    """
    
    def __init__(self, app, db_session_maker):
        """
        Инициализация загрузчика.
        
        Args:
            app: FastAPI приложение
            db_session_maker: async_sessionmaker для БД
        """
        self.app = app
        self.db_session_maker = db_session_maker
        self.event_bus = event_bus
        self.plugins: Dict[str, PluginBase] = {}
    
    async def load_all(self):
        """Загрузить все плагины из папки plugins/."""
        try:
            import plugins as plugins_package
        except ImportError:
            logger.warning("❌ plugins package not found, skipping plugin loading")
            return
        
        # Найти все подмодули в пакете plugins
        plugin_modules = list(pkgutil.iter_modules(
            plugins_package.__path__,
            prefix=plugins_package.__name__ + "."
        ))
        
        if not plugin_modules:
            logger.info("ℹ️ No plugins found in plugins/ directory")
            return
        
        logger.info(f"🔍 Found {len(plugin_modules)} plugin module(s)")
        
        for _, module_name, _ in plugin_modules:
            await self.load_plugin(module_name)
    
    async def load_plugin(self, module_name: str):
        """
        Загрузить конкретный плагин из модуля.
        
        Ищет в модуле класс, наследующий PluginBase, и инициализирует его.
        
        Args:
            module_name: Полное имя модуля (например: "plugins.devices_plugin")
        """
        try:
            logger.debug(f"Loading plugin from module: {module_name}")
            
            # Импортируем модуль
            module = importlib.import_module(module_name)
            
            # Ищем класс плагина (наследник InternalPluginBase)
            plugin_class = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and 
                    issubclass(attr, InternalPluginBase) and 
                    attr is not InternalPluginBase):
                    plugin_class = attr
                    break
            
            if not plugin_class:
                logger.warning(f"⚠️ No InternalPluginBase subclass found in {module_name}")
                return
            
            # Создаём экземпляр плагина
            plugin = plugin_class(self.app, self.db_session_maker, self.event_bus)
            
            # Вызываем on_load
            await plugin.on_load()
            
            # Регистрируем router если он есть
            if plugin.router:
                self.app.include_router(
                    plugin.router,
                    prefix=f"/api/v1/plugins/{plugin.id}",
                    tags=[plugin.name]
                )
                logger.debug(f"  📍 Registered router at /api/v1/plugins/{plugin.id}")
            
            # Сохраняем в реестр
            self.plugins[plugin.id] = plugin
            
            logger.info(f"✅ Loaded plugin: {plugin.name} v{plugin.version}")
            
        except Exception as e:
            logger.error(
                f"❌ Failed to load plugin from {module_name}: {e}",
                exc_info=True
            )
    
    async def unload_plugin(self, plugin_id: str):
        """
        Выгрузить плагин.
        
        Args:
            plugin_id: ID плагина (должен совпадать с plugin.id)
        """
        if plugin_id not in self.plugins:
            logger.warning(f"⚠️ Plugin '{plugin_id}' not found")
            return
        
        plugin = self.plugins[plugin_id]
        try:
            await plugin.on_unload()
            del self.plugins[plugin_id]
            logger.info(f"✅ Unloaded plugin: {plugin.name}")
        except Exception as e:
            logger.error(f"❌ Error unloading plugin {plugin_id}: {e}", exc_info=True)
    
    def get_plugin(self, plugin_id: str) -> Optional[InternalPluginBase]:
        """
        Получить экземпляр плагина по ID.
        
        Args:
            plugin_id: ID плагина
            
        Returns:
            PluginBase или None если не найден
        """
        return self.plugins.get(plugin_id)
    
    def list_plugins(self) -> List[Dict[str, str]]:
        """
        Получить список всех загруженных плагинов.
        
        Returns:
            Список словарей с информацией о плагинах
        """
        return [
            {
                "id": p.id,
                "name": p.name,
                "version": p.version,
                "description": p.description,
                "type": "internal"
            }
            for p in self.plugins.values()
        ]
