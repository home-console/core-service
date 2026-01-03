"""
Основной модуль загрузки плагинов.

Координирует работу всех модулей плагин-системы:
- plugin_finder: поиск плагинов
- metadata_reader: чтение метаданных
- archive_handler: работа с архивами
- installer: установка зависимостей
- router_manager: монтирование роутеров
- db_manager: работа с БД
"""

import importlib
import importlib.util
import logging
import os
import sys
import asyncio
import tempfile
import shutil
import subprocess
from typing import Dict, List, Optional, Any
from pathlib import Path

from .core.base import InternalPluginBase
try:
    from ..event_bus import EventBus
    from ..models import Device, PluginBinding, IntentMapping, Plugin, PluginVersion
    from ..db import get_session
except ImportError:
    from core_service.event_bus import EventBus
    from core_service.models import Device, PluginBinding, IntentMapping, Plugin, PluginVersion
    from core_service.db import get_session

from .plugin_finder import PluginFinder
from .metadata_reader import PluginMetadataReader
from .archive_handler import ArchiveHandler
from .installer import PluginDependencyInstaller
from .router_manager import PluginRouterManager
from .db_manager import PluginDBManager

logger = logging.getLogger(__name__)


class PluginLoader:
    """
    Загрузчик плагинов (встроенных и внешних).
    
    Использует модульную архитектуру для разделения ответственности.
    """
    
    def __init__(self, app, db_session_maker, event_bus: Optional[EventBus] = None):
        """
        Инициализация загрузчика.
        
        Args:
            app: FastAPI приложение
            db_session_maker: async_sessionmaker для БД
            event_bus: EventBus экземпляр (создается автоматически если не передан)
        """
        self.app = app
        self.db_session_maker = db_session_maker
        # Создаем event_bus если не передан (для обратной совместимости)
        if event_bus is None:
            self.event_bus = EventBus()
        else:
            self.event_bus = event_bus
        self.plugins: Dict[str, InternalPluginBase] = {}
        
        # Директория с внешними плагинами (из переменной окружения)
        self.external_plugins_dir = os.getenv("PLUGINS_DIR")
        
        # Временная директория для распакованных архивов
        self.temp_dir = tempfile.mkdtemp(prefix="plugins_")
        
        # Lock для потокобезопасности
        self._lock = asyncio.Lock()
        
        # Инициализация менеджеров
        self.archive_handler = ArchiveHandler(self.temp_dir)
        self.router_manager = PluginRouterManager(app, self._lock)
        
        logger.info(f"🔌 PluginLoader initialized")
        if self.external_plugins_dir:
            logger.info(f"📂 External plugins directory: {self.external_plugins_dir}")
        else:
            logger.info(f"📂 No external plugins directory set (PLUGINS_DIR env var)")
    
    async def load_all(self):
        """Загрузить все плагины: встроенные и внешние."""
        # 1. Загружаем встроенные плагины из core-service/plugins/
        await self._load_builtin_plugins()
        
        # 2. Загружаем внешние плагины если PLUGINS_DIR задана
        if self.external_plugins_dir:
            await self._load_external_plugins()
    
    async def _load_builtin_plugins(self):
        """Загрузить встроенные плагины из core-service/plugins/ (параллельно)"""
        plugin_modules = PluginFinder.find_builtin_plugins()
        
        if not plugin_modules:
            return
        
        # Параллельная загрузка с ограничением concurrency
        semaphore = asyncio.Semaphore(5)  # Максимум 5 плагинов одновременно
        
        async def load_single_plugin(module_name: str, is_package: bool) -> tuple[str, bool, Optional[Exception]]:
            """Загрузить один плагин с изоляцией ошибок"""
            async with semaphore:
                try:
                    if is_package:
                        # Для пакетов проверяем и устанавливаем зависимости
                        try:
                            plugin_dir_name = module_name.split('.')[-1]
                            # Получаем путь к плагину
                            try:
                                import core_service.plugins as plugins_package
                                base_path = plugins_package.__path__[0]
                            except ImportError:
                                import plugins as plugins_package
                                base_path = plugins_package.__path__[0]
                            
                            plugin_path = os.path.join(base_path, plugin_dir_name)
                            if os.path.isdir(plugin_path):
                                requirements_file = os.path.join(plugin_path, 'requirements.txt')
                                if os.path.exists(requirements_file):
                                    logger.info(f"📦 Found requirements.txt for builtin plugin {plugin_dir_name}, installing dependencies...")
                                    deps_result = await asyncio.to_thread(
                                        PluginDependencyInstaller.install_dependencies,
                                        plugin_path,
                                        plugin_dir_name
                                    )
                                    if deps_result.get('status') == 'installed':
                                        logger.info(f"✅ Dependencies installed for plugin {plugin_dir_name}")
                                    elif deps_result.get('status') == 'failed':
                                        logger.warning(f"⚠️ Failed to install dependencies for {plugin_dir_name}: {deps_result.get('error')}")
                        except Exception as e:
                            logger.debug(f"Could not check/install dependencies for {module_name}: {e}")
                        
                        # Пробуем загрузить модуль и найти класс плагина
                        try:
                            module = importlib.import_module(module_name)
                            plugin_class = self._find_plugin_class(module)
                            
                            if plugin_class:
                                logger.info(f"🔄 Attempting to load plugin from package: {module_name}")
                                await self.load_plugin(module_name, plugin_type="builtin")
                                return (module_name, True, None)
                            else:
                                logger.debug(f"⏭️ No plugin class found in package: {module_name}")
                                return (module_name, False, None)
                        except Exception as e:
                            logger.error(f"❌ Failed to load plugin package {module_name}: {e}", exc_info=True)
                            return (module_name, False, e)
                    else:
                        # Обычный модуль (файл .py)
                        logger.info(f"🔄 Attempting to load plugin: {module_name}")
                        try:
                            await self.load_plugin(module_name, plugin_type="builtin")
                            return (module_name, True, None)
                        except Exception as e:
                            logger.error(f"❌ Failed to load plugin {module_name}: {e}", exc_info=True)
                            return (module_name, False, e)
                except Exception as e:
                    logger.error(f"❌ Unexpected error loading plugin {module_name}: {e}", exc_info=True)
                    return (module_name, False, e)
        
        # Загружаем все плагины параллельно
        tasks = [
            load_single_plugin(module_name, is_package)
            for module_name, is_package in plugin_modules
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Подсчитываем успешно загруженные
        loaded_count = 0
        failed_count = 0
        for result in results:
            if isinstance(result, Exception):
                failed_count += 1
                logger.error(f"Plugin loading task failed: {result}", exc_info=True)
            elif isinstance(result, tuple):
                module_name, success, error = result
                if success:
                    loaded_count += 1
                else:
                    failed_count += 1
            if is_package:
                # Для пакетов проверяем и устанавливаем зависимости
                try:
                    plugin_dir_name = module_name.split('.')[-1]
                    # Получаем путь к плагину
                    try:
                        import core_service.plugins as plugins_package
                        base_path = plugins_package.__path__[0]
                    except ImportError:
                        import plugins as plugins_package
                        base_path = plugins_package.__path__[0]
                    
                    plugin_path = os.path.join(base_path, plugin_dir_name)
                    if os.path.isdir(plugin_path):
                        requirements_file = os.path.join(plugin_path, 'requirements.txt')
                        if os.path.exists(requirements_file):
                            logger.info(f"📦 Found requirements.txt for builtin plugin {plugin_dir_name}, installing dependencies...")
                            deps_result = await asyncio.to_thread(
                                PluginDependencyInstaller.install_dependencies,
                                plugin_path,
                                plugin_dir_name
                            )
                            if deps_result.get('status') == 'installed':
                                logger.info(f"✅ Dependencies installed for plugin {plugin_dir_name}")
                            elif deps_result.get('status') == 'failed':
                                logger.warning(f"⚠️ Failed to install dependencies for {plugin_dir_name}: {deps_result.get('error')}")
                except Exception as e:
                    logger.debug(f"Could not check/install dependencies for {module_name}: {e}")
                
                # Пробуем загрузить модуль и найти класс плагина
                try:
                    module = importlib.import_module(module_name)
                    plugin_class = self._find_plugin_class(module)
                    
                    if plugin_class:
                        logger.info(f"🔄 Attempting to load plugin from package: {module_name}")
                        await self.load_plugin(module_name, plugin_type="builtin")
                        loaded_count += 1
                    else:
                        logger.debug(f"⏭️ No plugin class found in package: {module_name}")
                except Exception as e:
                    logger.error(f"❌ Failed to load plugin package {module_name}: {e}", exc_info=True)
            else:
                # Обычный модуль (файл .py)
                logger.info(f"🔄 Attempting to load plugin: {module_name}")
                try:
                    await self.load_plugin(module_name, plugin_type="builtin")
                    loaded_count += 1
                except Exception as e:
                    logger.error(f"❌ Failed to load plugin {module_name}: {e}", exc_info=True)
        
        logger.info(f"✅ Successfully loaded {loaded_count} builtin plugin(s)")
        if failed_count > 0:
            logger.warning(f"⚠️ Failed to load {failed_count} builtin plugin(s)")
    
    async def _load_external_plugins(self):
        """Загрузить внешние плагины из PLUGINS_DIR"""
        plugin_paths = PluginFinder.find_external_plugins(self.external_plugins_dir)
        
        for item_path in plugin_paths:
            item_name = os.path.basename(item_path)
            await self._load_external_item(item_path, item_name)
    
    async def _load_external_item(self, item_path: str, item_name: str):
        """Загрузить внешний плагин (может быть папка, файл или архив)."""
        if os.path.isdir(item_path):
            await self._load_external_package(item_path, item_name)
        elif item_path.endswith('.py'):
            await self._load_external_python_file(item_path)
        elif item_path.endswith('.zip'):
            await self._load_external_archive(item_path, 'zip')
        elif item_path.endswith(('.tar.gz', '.tgz')):
            await self._load_external_archive(item_path, 'tar')
        else:
            logger.debug(f"⏭️ Skipping unknown file type: {item_name}")
    
    async def _load_external_package(self, package_path: str, package_name: str):
        """Загрузить внешний плагин из папки (package)."""
        plugin_json_path = os.path.join(package_path, "plugin.json")
        
        if not os.path.exists(plugin_json_path):
            logger.warning(f"⚠️ plugin.json not found in {package_path}")
            return
        
        try:
            metadata = PluginMetadataReader.read_metadata(plugin_json_path)
            if not metadata:
                return
            
            entry_file = PluginFinder.find_entry_file(package_path)
            if not entry_file:
                return
            
            await self._load_python_module_file(entry_file, metadata)
            
        except Exception as e:
            logger.error(f"❌ Error loading external package {package_name}: {e}", exc_info=True)
    
    async def _load_external_python_file(self, file_path: str):
        """Загрузить внешний плагин из одного Python файла."""
        try:
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            plugin_json_path = os.path.join(os.path.dirname(file_path), f"{base_name}.json")
            
            metadata = None
            if os.path.exists(plugin_json_path):
                metadata = PluginMetadataReader.read_metadata(plugin_json_path)
            
            if not metadata:
                metadata = PluginMetadataReader.create_default_metadata(base_name)
            
            await self._load_python_module_file(file_path, metadata)
            
        except Exception as e:
            logger.error(f"❌ Error loading external Python file {file_path}: {e}", exc_info=True)
    
    async def _load_external_archive(self, archive_path: str, archive_type: str):
        """Загрузить внешний плагин из архива."""
        try:
            extract_dir = self.archive_handler.extract_archive(archive_path, archive_type)
            if not extract_dir:
                return
            
            plugin_json_path = os.path.join(extract_dir, "plugin.json")
            if not os.path.exists(plugin_json_path):
                logger.warning(f"⚠️ plugin.json not found in archive {os.path.basename(archive_path)}")
                return
            
            metadata = PluginMetadataReader.read_metadata(plugin_json_path)
            if not metadata:
                return
            
            main_file = os.path.join(extract_dir, "main.py")
            if not os.path.exists(main_file):
                logger.warning(f"⚠️ main.py not found in archive {os.path.basename(archive_path)}")
                return
            
            await self._load_python_module_file(main_file, metadata)
            
        except Exception as e:
            logger.error(f"❌ Error loading archive {os.path.basename(archive_path)}: {e}", exc_info=True)
    
    def _find_plugin_class(self, module) -> Optional[type]:
        """Найти класс плагина в модуле."""
        # Сначала проверяем, есть ли класс в __all__ или экспортирован напрямую
        if hasattr(module, '__all__'):
            for attr_name in module.__all__:
                attr = getattr(module, attr_name, None)
                if (isinstance(attr, type) and 
                    issubclass(attr, InternalPluginBase) and 
                    attr is not InternalPluginBase):
                    return attr
        
        # Если не нашли, ищем во всех атрибутах модуля
        for attr_name in dir(module):
            if attr_name.startswith('_'):
                continue
            attr = getattr(module, attr_name)
            if (isinstance(attr, type) and 
                issubclass(attr, InternalPluginBase) and 
                attr is not InternalPluginBase):
                return attr
        
        return None
    
    async def _load_python_module_file(self, file_path: str, metadata: Dict[str, Any]):
        """
        Загрузить Python модуль из файла.
        
        Args:
            file_path: Путь к Python файлу
            metadata: Метаданные плагина из plugin.json
        """
        try:
            # Генерируем уникальное имя для модуля
            module_name = f"external_plugin_{metadata['id']}_{id(file_path)}"
            
            # Загружаем модуль
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if not spec or not spec.loader:
                logger.error(f"❌ Failed to load spec from {file_path}")
                return
            
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            
            logger.debug(f"✅ Loaded module: {module_name} from {file_path}")
            
            # Ищем класс плагина
            plugin_class = self._find_plugin_class(module)
            
            if not plugin_class:
                logger.warning(f"⚠️ No InternalPluginBase subclass found in {os.path.basename(file_path)}")
                return
            
            # Подготавливаем модели для передачи в плагин
            models_dict = {
                'Device': Device,
                'PluginBinding': PluginBinding,
                'IntentMapping': IntentMapping,
                'Plugin': Plugin,
                'PluginVersion': PluginVersion,
            }
            
            # Создаём экземпляр плагина
            plugin = plugin_class(self.app, self.db_session_maker, self.event_bus, models=models_dict)
            
            # Проверяем, включен ли плагин в БД
            if not await PluginDBManager.is_plugin_enabled(plugin.id):
                logger.info(f"⏭️ Plugin {plugin.id} is disabled in DB, skipping load")
                return
            
            # Обновляем метаданные из plugin.json
            if metadata.get('name'):
                plugin.name = metadata['name']
            if metadata.get('version'):
                plugin.version = metadata['version']
            if metadata.get('description'):
                plugin.description = metadata.get('description', '')
            
            plugin.manifest = metadata
            if metadata.get('type'):
                plugin.type = metadata['type']
            
            # Вызываем on_load
            try:
                await plugin.on_load()
                plugin._is_loaded = True
            except Exception as e:
                logger.error(f"⚠️ Plugin on_load failed for {plugin.id}: {e}", exc_info=True)
                return
            
            # Монтируем роутер через router_manager
            if plugin.router:
                await self.router_manager.mount_router(
                    plugin.id,
                    plugin.name,
                    plugin.router,
                    metadata
                )
            
            # Сохраняем в реестр
            try:
                async with self._lock:
                    self.plugins[plugin.id] = plugin
            except Exception:
                self.plugins[plugin.id] = plugin
            
            # Сохраняем информацию о плагине в БД
            await PluginDBManager.save_plugin(plugin, manifest=metadata, plugin_type=metadata.get('type'))
            
            logger.info(f"✅ Loaded external plugin: {plugin.name} v{plugin.version}")
            
        except Exception as e:
            logger.error(f"❌ Failed to load module from {file_path}: {e}", exc_info=True)
    
    async def load_plugin(self, module_name: str, plugin_type: str = "builtin"):
        """
        Загрузить встроенный плагин из модуля.
        
        Args:
            module_name: Полное имя модуля (например: "plugins.devices_plugin")
            plugin_type: "builtin" или "external"
        """
        try:
            logger.debug(f"Loading {plugin_type} plugin from module: {module_name}")
            
            # Импортируем модуль
            module = importlib.import_module(module_name)
            
            # Ищем класс плагина
            plugin_class = self._find_plugin_class(module)
            
            if not plugin_class:
                logger.warning(f"⚠️ No InternalPluginBase subclass found in {module_name}")
                return
            
            # Подготавливаем модели
            models_dict = {
                'Device': Device,
                'PluginBinding': PluginBinding,
                'IntentMapping': IntentMapping,
                'Plugin': Plugin,
                'PluginVersion': PluginVersion,
            }
            
            # Создаём экземпляр плагина
            plugin = plugin_class(self.app, self.db_session_maker, self.event_bus, models=models_dict)
            
            # Проверяем, включен ли плагин в БД
            if not await PluginDBManager.is_plugin_enabled(plugin.id):
                logger.info(f"⏭️ Plugin {plugin.id} is disabled in DB, skipping load")
                return
            
            # Подтягиваем сохраненную конфигурацию из БД
            await self._apply_plugin_config(plugin)
            
            # Пытаемся загрузить manifest.json для встроенных плагинов
            if plugin_type == "builtin" and hasattr(module, '__file__'):
                module_file = module.__file__
                if module_file:
                    module_dir = os.path.dirname(module_file)
                    manifest_path = os.path.join(module_dir, "manifest.json")
                    if os.path.exists(manifest_path):
                        try:
                            manifest_data = PluginMetadataReader.read_metadata(manifest_path)
                            if manifest_data:
                                plugin.manifest = manifest_data
                                if manifest_data.get('type'):
                                    plugin.type = manifest_data.get('type')
                                logger.debug(f"📋 Loaded manifest.json for {plugin.id}")
                        except Exception as e:
                            logger.debug(f"⚠️ Failed to load manifest.json for {plugin.id}: {e}")
            
            # Вызываем on_load
            try:
                await plugin.on_load()
                plugin._is_loaded = True
            except Exception as e:
                logger.error(f"⚠️ Plugin on_load failed for {plugin.id}: {e}", exc_info=True)
                return
            
            # Монтируем роутер
            if plugin.router:
                manifest = getattr(plugin, 'manifest', None) or {}
                await self.router_manager.mount_router(
                    plugin.id,
                    plugin.name,
                    plugin.router,
                    manifest
                )
            
            # Сохраняем в реестр
            try:
                async with self._lock:
                    self.plugins[plugin.id] = plugin
            except Exception:
                self.plugins[plugin.id] = plugin
            
            # Сохраняем информацию о плагине в БД
            manifest = getattr(plugin, 'manifest', None) or {}
            await PluginDBManager.save_plugin(plugin, manifest=manifest, plugin_type=plugin_type)
            
            logger.info(f"✅ Loaded {plugin_type} plugin: {plugin.name} v{plugin.version}")
            
        except Exception as e:
            logger.error(
                f"❌ Failed to load {plugin_type} plugin from {module_name}: {e}",
                exc_info=True
            )
    
    async def _apply_plugin_config(self, plugin):
        """Применить сохраненную конфигурацию плагина из БД."""
        try:
            # Получаем глобальную конфигурацию из PluginConfigManager если доступен
            global_config = {}
            if hasattr(self.app.state, 'plugin_config_manager'):
                try:
                    config_manager = self.app.state.plugin_config_manager
                    plugin_config = await config_manager.get_config(plugin.id)
                    if plugin_config:
                        global_config = {
                            'device_online_timeout': plugin_config.device_online_timeout,
                            'device_poll_interval': plugin_config.device_poll_interval
                        }
                        logger.debug(f"📋 Global device settings for {plugin.id}: online_timeout={plugin_config.device_online_timeout}s, poll_interval={plugin_config.device_poll_interval}s")
                except Exception as e:
                    logger.debug(f"Could not get global config for {plugin.id}: {e}")
            
            async with get_session() as db:
                from sqlalchemy import select
                existing_q = await db.execute(select(Plugin).where(Plugin.id == plugin.id))
                existing = existing_q.scalar_one_or_none()
                
                # Инициализируем base_cfg
                base_cfg = getattr(plugin, "config", None) or {}
                if not isinstance(base_cfg, dict):
                    try:
                        if hasattr(base_cfg, '_config_cache'):
                            base_cfg = dict(getattr(base_cfg, '_config_cache') or {})
                        elif hasattr(base_cfg, 'dict') and callable(getattr(base_cfg, 'dict')):
                            base_cfg = base_cfg.dict()
                        elif hasattr(base_cfg, 'config') and isinstance(base_cfg.config, dict):
                            base_cfg = base_cfg.config.copy()
                        else:
                            base_cfg = {}
                    except Exception:
                        base_cfg = {}
                
                if existing and existing.config:
                    persisted = existing.config if isinstance(existing.config, dict) else {}
                    merged = {**base_cfg, **persisted, **global_config}
                    logger.info(f"🔧 Applied persisted config for plugin {plugin.id}: {persisted}")
                else:
                    merged = {**base_cfg, **global_config}
                    logger.info(f"ℹ️ No persisted config found for plugin {plugin.id}, using defaults + global settings")
                
                # Обновляем конфигурацию плагина
                if hasattr(plugin.config, 'config') and isinstance(plugin.config.config, dict):
                    plugin.config.config.update(merged)
                else:
                    plugin.config = merged
        except Exception as e:
            logger.warning(f"⚠️ Failed to apply persisted config for plugin {plugin.id}: {e}")
    
    async def unload_plugin(self, plugin_id: str):
        """
        Выгрузить плагин.
        
        Args:
            plugin_id: ID плагина
        """
        if plugin_id not in self.plugins:
            logger.warning(f"⚠️ Plugin '{plugin_id}' not found")
            return
        
        plugin = self.plugins[plugin_id]
        try:
            # Размонтируем роутер
            await self.router_manager.unmount_router(plugin_id)
            
            # Вызываем on_unload плагина
            await plugin.on_unload()
            
            # Удаляем из реестра
            try:
                async with self._lock:
                    if plugin_id in self.plugins:
                        del self.plugins[plugin_id]
            except Exception:
                if plugin_id in self.plugins:
                    del self.plugins[plugin_id]
            
            # Обновляем статус в БД
            await PluginDBManager.update_loaded_status(plugin_id, loaded=False)
            
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
                "type": getattr(p, 'type', 'internal') or 'internal',
                "loaded": True
            }
            for p in self.plugins.values()
        ]
    
    async def install_from_url(self, url: str) -> Dict[str, Any]:
        """Установить плагин из URL (zip/tar.gz файл)."""
        import httpx
        
        if not self.external_plugins_dir:
            raise ValueError("PLUGINS_DIR not configured")
        
        os.makedirs(self.external_plugins_dir, exist_ok=True)
        logger.info(f"📥 Downloading plugin from {url}")
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()
            
            filename = url.split('/')[-1].split('?')[0]
            if not filename.endswith(('.zip', '.tar.gz', '.tgz')):
                content_type = response.headers.get('content-type', '')
                filename += '.zip' if 'zip' in content_type else '.tar.gz'
            
            temp_path = os.path.join(tempfile.gettempdir(), filename)
            with open(temp_path, 'wb') as f:
                f.write(response.content)
            
            before = set(self.plugins.keys())
            archive_type = 'zip' if filename.endswith('.zip') else 'tar'
            await self._load_external_archive(temp_path, archive_type)
            after = set(self.plugins.keys())
            new = list(after - before)
            
            # Install dependencies for newly loaded plugins
            deps_results = {}
            for plugin_id in new:
                plugin_path = os.path.join(self.external_plugins_dir, plugin_id)
                if os.path.isdir(plugin_path):
                    deps_result = await asyncio.to_thread(
                        PluginDependencyInstaller.install_dependencies,
                        plugin_path,
                        plugin_id
                    )
                    deps_results[plugin_id] = deps_result
            
            logger.info(f"✅ Plugin installed from {url}")
            res: Dict[str, Any] = {'status': 'installed', 'source': url}
            if new:
                res['plugin_ids'] = new
                if len(new) == 1:
                    res['plugin_id'] = new[0]
            if deps_results:
                res['dependencies'] = deps_results
            return res
            
        except Exception as e:
            logger.error(f"❌ Failed to install plugin from URL: {e}", exc_info=True)
            raise
    
    async def install_from_local(self, path: str) -> Dict[str, Any]:
        """Установить плагин из локального файла/папки."""
        if not os.path.exists(path):
            raise FileNotFoundError(f'Plugin path not found: {path}')
        
        if not self.external_plugins_dir:
            raise ValueError('PLUGINS_DIR not configured')
        
        os.makedirs(self.external_plugins_dir, exist_ok=True)
        logger.info(f'📁 Installing plugin from {path}')
        
        try:
            before = set(self.plugins.keys())
            
            if os.path.isdir(path):
                plugin_name = os.path.basename(path)
                dest_path = os.path.join(self.external_plugins_dir, plugin_name)
                if os.path.exists(dest_path):
                    shutil.rmtree(dest_path)
                shutil.copytree(path, dest_path)
                deps_result = await asyncio.to_thread(
                    PluginDependencyInstaller.install_dependencies,
                    dest_path,
                    plugin_name
                )
                await self._load_external_package(dest_path, plugin_name)
            elif path.endswith('.py'):
                filename = os.path.basename(path)
                dest_path = os.path.join(self.external_plugins_dir, filename)
                shutil.copy2(path, dest_path)
                await self._load_external_python_file(dest_path)
            elif path.endswith('.zip'):
                await self._load_external_archive(path, 'zip')
            elif path.endswith(('.tar.gz', '.tgz')):
                await self._load_external_archive(path, 'tar')
            else:
                raise ValueError(f'Unsupported file type: {path}')
            
            after = set(self.plugins.keys())
            new = list(after - before)
            
            logger.info(f'✅ Plugin installed from {path}')
            res: Dict[str, Any] = {'status': 'installed', 'source': path}
            if new:
                res['plugin_ids'] = new
                if len(new) == 1:
                    res['plugin_id'] = new[0]
            return res
            
        except Exception as e:
            logger.error(f'❌ Failed to install plugin from local path: {e}', exc_info=True)
            raise
    
    def install_from_git(self, git_url: str) -> Dict[str, Any]:
        """Синхронная установка плагина из git-репозитория."""
        import json
        
        if not self.external_plugins_dir:
            raise ValueError('PLUGINS_DIR not configured')
        
        os.makedirs(self.external_plugins_dir, exist_ok=True)
        tmp_clone = tempfile.mkdtemp(prefix='plugin_clone_')
        
        try:
            logger.info(f"📥 Cloning plugin from git {git_url}")
            subprocess.check_call(["git", "clone", "--depth", "1", git_url, tmp_clone])
            
            plugin_root = tmp_clone
            if not os.path.exists(os.path.join(plugin_root, 'plugin.json')):
                entries = [e for e in os.listdir(tmp_clone) if not e.startswith('.')]
                if len(entries) == 1:
                    candidate = os.path.join(tmp_clone, entries[0])
                    if os.path.exists(os.path.join(candidate, 'plugin.json')):
                        plugin_root = candidate
            
            plugin_json = os.path.join(plugin_root, 'plugin.json')
            if not os.path.exists(plugin_json):
                raise FileNotFoundError('plugin.json not found in cloned repository')
            
            metadata = PluginMetadataReader.read_metadata(plugin_json)
            if not metadata:
                raise ValueError('Invalid plugin.json')
            
            plugin_id = metadata.get('id') or os.path.basename(git_url).replace('.git', '')
            dest_path = os.path.join(self.external_plugins_dir, plugin_id)
            
            if os.path.exists(dest_path):
                shutil.rmtree(dest_path)
            
            shutil.copytree(plugin_root, dest_path)
            
            deps_result = PluginDependencyInstaller.install_dependencies(dest_path, plugin_id)
            
            # Загружаем плагин синхронно (вызывается через asyncio.to_thread)
            import asyncio as _asyncio
            _asyncio.run(self._load_external_package(dest_path, plugin_id))
            
            logger.info(f"✅ Plugin installed from git {git_url}")
            result = {'status': 'installed', 'source': git_url, 'plugin_id': plugin_id}
            if deps_result.get('status') == 'installed':
                result['dependencies'] = 'installed'
            elif deps_result.get('status') == 'failed':
                result['dependencies'] = 'failed'
                result['dependencies_error'] = deps_result.get('error')
            return result
            
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Git clone failed: {e}", exc_info=True)
            raise
        finally:
            shutil.rmtree(tmp_clone, ignore_errors=True)
    
    async def reload_plugin(self, plugin_id: str) -> Dict[str, Any]:
        """Перезагрузить плагин."""
        logger.info(f'🔄 Reloading plugin {plugin_id}')
        
        # Если плагин загружен, выгружаем его
        if plugin_id in self.plugins:
            try:
                await self.unload_plugin(plugin_id)
            except Exception as e:
                logger.debug(f"⚠️ Failed to unload before reload: {e}")
        
        # Пытаемся найти модуль плагина
        plugin_modules = PluginFinder.find_builtin_plugins()
        module_name = None
        
        for mod_name, is_pkg in plugin_modules:
            parts = mod_name.split('.')
            last_part = parts[-1]
            if last_part == plugin_id:
                module_name = mod_name
                break
        
        if module_name:
            await self.load_plugin(module_name, plugin_type='builtin')
            logger.info(f'✅ Reloaded builtin plugin {plugin_id}')
            return {'status': 'reloaded', 'plugin_id': plugin_id, 'type': 'builtin'}
        
        # Пробуем внешние плагины
        if self.external_plugins_dir:
            await self._load_external_plugins()
            if plugin_id in self.plugins:
                logger.info(f'✅ Reloaded external plugin {plugin_id}')
                return {'status': 'reloaded', 'plugin_id': plugin_id, 'type': 'external'}
        
        raise ValueError(f'Plugin {plugin_id} not found')
    
    def __del__(self):
        """Cleanup temp directory on destruction."""
        try:
            if hasattr(self, 'archive_handler'):
                self.archive_handler.cleanup()
            elif hasattr(self, 'temp_dir') and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass

