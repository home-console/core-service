"""
PluginLoader: загрузка плагинов из встроенной папки и внешних директорий.

Поддерживает:
- Встроенные плагины: core-service/plugins/ (Python модули)
- Внешние плагины: через PLUGINS_DIR переменную окружения
- Форматы: Python файлы, папки (packages), архивы (.zip, .tar.gz)
- Метаданные: plugin.json в каждой папке плагина
"""

import importlib
import importlib.util
import pkgutil
import logging
import os
import sys
import json
import zipfile
import tarfile
import tempfile
import shutil
import subprocess
import asyncio
import site
from pathlib import Path
from typing import Dict, List, Optional, Any
from sqlalchemy import select
from .plugin_base import InternalPluginBase
try:
    from .event_bus import event_bus
    from .models import Plugin, PluginVersion, Device, PluginBinding, IntentMapping
    from .db import get_session
except ImportError:
    from core_service.event_bus import event_bus
    from core_service.models import Plugin, PluginVersion, Device, PluginBinding, IntentMapping
    from core_service.db import get_session

logger = logging.getLogger(__name__)


class PluginLoader:
    """
    Загрузчик плагинов (встроенных и внешних).
    
    Загружает плагины из:
    1. core-service/plugins/ — встроенные плагины (Python модули)
    2. PLUGINS_DIR — внешние плагины (если переменная окружения задана)
    
    Поддерживаемые форматы внешних плагинов:
    - Папка с plugin.json: plugins/my-plugin/
    - Python файл: plugins/my-plugin.py
    - ZIP архив: plugins/my-plugin.zip (должен содержать plugin.json в корне)
    - TAR.GZ архив: plugins/my-plugin.tar.gz (должен содержать plugin.json в корне)
    
    Структура plugin.json:
    ```json
    {
        "id": "my_plugin",
        "name": "My Plugin",
        "version": "1.0.0",
        "description": "Plugin description",
        "author": "Author Name",
        "type": "internal"  # или "external"
    }
    ```
    
    Переменные окружения:
    - PLUGINS_DIR: путь к директории с внешними плагинами (опционально)
    - Example: PLUGINS_DIR=/opt/plugins python main.py
    
    Пример использования:
    
    ```python
    # В main.py или admin_app.py
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
        self.plugins: Dict[str, InternalPluginBase] = {}
        
        # Словарь для отслеживания префиксов зарегистрированных роутеров плагинов
        # Ключ: plugin_id, Значение: префикс роутера (для удаления при выгрузке)
        self.plugin_routes: Dict[str, str] = {}
        
        # Директория с внешними плагинами (из переменной окружения)
        self.external_plugins_dir = os.getenv("PLUGINS_DIR")
        
        # Временная директория для распакованных архивов
        self.temp_dir = tempfile.mkdtemp(prefix="plugins_")
        # Lock to protect concurrent access to self.plugins and plugin_routes
        self._lock = asyncio.Lock()
        
        logger.info(f"🔌 PluginLoader initialized")
        if self.external_plugins_dir:
            logger.info(f"📂 External plugins directory: {self.external_plugins_dir}")
        else:
            logger.info(f"📂 No external plugins directory set (PLUGINS_DIR env var)")
        # Note: Admin endpoints are now handled by routes/plugins.py
        # This avoids route conflicts when plugins router is mounted
    
    async def load_all(self):
        """Загрузить все плагины: встроенные и внешние."""
        # 1. Загружаем встроенные плагины из core-service/plugins/
        await self._load_builtin_plugins()
        
        # 2. Загружаем внешние плагины если PLUGINS_DIR задана
        if self.external_plugins_dir:
            await self._load_external_plugins()
    
    async def _load_builtin_plugins(self):
        """Загрузить встроенные плагины из core-service/plugins/"""
        # Try different import paths
        plugins_package = None
        package_name = None
        
        # Try core_service.plugins first (when running as package)
        try:
            import core_service.plugins as plugins_package
            package_name = "core_service.plugins"
        except ImportError:
            try:
                # Fallback to plugins (when running from core-service directory)
                import plugins as plugins_package
                package_name = "plugins"
            except ImportError:
                logger.debug("plugins package not found, skipping builtin plugin loading")
                return
        
        # Найти все подмодули в пакете plugins (рекурсивно)
        try:
            plugin_modules = []
            # Используем walk_packages для рекурсивного поиска
            for importer, modname, ispkg in pkgutil.walk_packages(
                plugins_package.__path__,
                prefix=package_name + "."
            ):
                plugin_modules.append((modname, ispkg))
        except Exception as e:
            logger.warning(f"Failed to iterate plugin modules: {e}")
            return
        
        if not plugin_modules:
            logger.info("ℹ️ No builtin plugins found in plugins/ directory")
            return
        
        logger.info(f"🔍 Found {len(plugin_modules)} builtin plugin module(s)")
        
        # Filter out non-plugin modules (like __init__, base, loader, embed, models)
        excluded = {'__init__', 'base', 'loader', 'embed', 'models', 'utils'}
        # Patterns to exclude: examples, tests, generated files, utility scripts
        excluded_patterns = ['_example', 'example', '_test', 'test', 'generate_', 'setup', 'migration']
        loaded_count = 0
        for module_name, is_package in plugin_modules:
            module_basename = module_name.split('.')[-1]
            if module_basename in excluded:
                logger.debug(f"⏭️ Skipping excluded module: {module_name}")
                continue
            
            # Skip modules matching excluded patterns
            if any(pattern in module_basename.lower() for pattern in excluded_patterns):
                logger.debug(f"⏭️ Skipping module matching excluded pattern: {module_name}")
                continue
            
            # Для пакетов (подпапок) проверяем, есть ли в них класс плагина
            if is_package:
                # Сначала проверяем и устанавливаем зависимости перед импортом
                try:
                    # Получаем путь к папке плагина используя уже известный plugins_package
                    plugin_dir_name = module_name.split('.')[-1]
                    
                    if plugins_package and hasattr(plugins_package, '__path__'):
                        # Используем путь из plugins_package
                        base_path = plugins_package.__path__[0]
                        plugin_path = os.path.join(base_path, plugin_dir_name)
                        
                        if os.path.isdir(plugin_path):
                            # Проверяем requirements.txt и устанавливаем зависимости
                            requirements_file = os.path.join(plugin_path, 'requirements.txt')
                            if os.path.exists(requirements_file):
                                logger.info(f"📦 Found requirements.txt for builtin plugin {plugin_dir_name}, installing dependencies...")
                                deps_result = await asyncio.to_thread(
                                    self._install_plugin_dependencies, 
                                    plugin_path, 
                                    plugin_dir_name
                                )
                                if deps_result.get('status') == 'installed':
                                    logger.info(f"✅ Dependencies installed for plugin {plugin_dir_name}")
                                elif deps_result.get('status') == 'failed':
                                    logger.warning(f"⚠️ Failed to install dependencies for {plugin_dir_name}: {deps_result.get('error')}")
                                    # Продолжаем загрузку даже если зависимости не установились
                except Exception as e:
                    logger.debug(f"Could not check/install dependencies for {module_name}: {e}")
                    # Продолжаем загрузку даже если не удалось проверить зависимости
                
                # Пробуем загрузить модуль и найти класс плагина
                try:
                    module = importlib.import_module(module_name)
                    # Ищем класс плагина в модуле
                    plugin_class = None
                    for attr_name in dir(module):
                        if attr_name.startswith('_'):
                            continue
                        attr = getattr(module, attr_name)
                        if (isinstance(attr, type) and 
                            issubclass(attr, InternalPluginBase) and 
                            attr is not InternalPluginBase):
                            plugin_class = attr
                            break
                    
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
    
    async def _load_external_plugins(self):
        """Загрузить внешние плагины из PLUGINS_DIR"""
        if not os.path.isdir(self.external_plugins_dir):
            logger.warning(f"❌ PLUGINS_DIR not found: {self.external_plugins_dir}")
            return
        
        items = os.listdir(self.external_plugins_dir)
        
        if not items:
            logger.info(f"ℹ️ PLUGINS_DIR is empty: {self.external_plugins_dir}")
            return
        
        logger.info(f"🔍 Scanning PLUGINS_DIR for plugins: {self.external_plugins_dir}")
        
        for item in sorted(items):
            item_path = os.path.join(self.external_plugins_dir, item)
            
            # Пропускаем скрытые файлы и __pycache__
            if item.startswith('.') or item == '__pycache__':
                continue
            
            await self._load_external_item(item_path, item)
    
    async def _load_external_item(self, item_path: str, item_name: str):
        """
        Загрузить внешний плагин (может быть папка, файл или архив).
        
        Args:
            item_path: Полный путь к элементу
            item_name: Имя элемента (без пути)
        """
        if os.path.isdir(item_path):
            # Это папка - загружаем как package
            await self._load_external_package(item_path, item_name)
        
        elif item_path.endswith('.py'):
            # Это Python файл
            await self._load_external_python_file(item_path)
        
        elif item_path.endswith('.zip'):
            # Это ZIP архив
            await self._load_external_archive(item_path, 'zip')
        
        elif item_path.endswith(('.tar.gz', '.tgz')):
            # Это TAR.GZ архив
            await self._load_external_archive(item_path, 'tar')
        
        else:
            logger.debug(f"⏭️ Skipping unknown file type: {item_name}")
    
    async def _load_external_package(self, package_path: str, package_name: str):
        """Загрузить внешний плагин из папки (package)."""
        # Ищем plugin.json в папке
        plugin_json_path = os.path.join(package_path, "plugin.json")
        
        if not os.path.exists(plugin_json_path):
            logger.warning(f"⚠️ plugin.json not found in {package_path}")
            return
        
        try:
            metadata = self._read_plugin_metadata(plugin_json_path)
            if not metadata:
                return
            
            # Проверяем наличие main.py или __init__.py
            main_file = os.path.join(package_path, "main.py")
            init_file = os.path.join(package_path, "__init__.py")
            
            if os.path.exists(main_file):
                entry_file = main_file
            elif os.path.exists(init_file):
                entry_file = init_file
            else:
                logger.warning(f"⚠️ No main.py or __init__.py found in {package_path}")
                return
            
            await self._load_python_module_file(entry_file, metadata)
            
        except Exception as e:
            logger.error(f"❌ Error loading external package {package_name}: {e}", exc_info=True)
    
    async def _load_external_python_file(self, file_path: str):
        """Загрузить внешний плагин из одного Python файла."""
        try:
            # Пытаемся найти plugin.json рядом с файлом
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            plugin_json_path = os.path.join(
                os.path.dirname(file_path),
                f"{base_name}.json"
            )
            
            metadata = None
            if os.path.exists(plugin_json_path):
                metadata = self._read_plugin_metadata(plugin_json_path)
            
            # Если нет metadata, используем имя файла
            if not metadata:
                metadata = {
                    "id": base_name,
                    "name": base_name.replace('_', ' ').title(),
                    "version": "1.0.0",
                    "type": "internal"
                }
            
            await self._load_python_module_file(file_path, metadata)
            
        except Exception as e:
            logger.error(f"❌ Error loading external Python file {file_path}: {e}", exc_info=True)
    
    async def _load_external_archive(self, archive_path: str, archive_type: str):
        """
        Загрузить внешний плагин из архива.
        
        Args:
            archive_path: Путь к архиву
            archive_type: 'zip' или 'tar'
        """
        try:
            # Создаем временную папку для распаковки
            extract_dir = os.path.join(self.temp_dir, os.path.splitext(
                os.path.basename(archive_path)
            )[0])
            
            os.makedirs(extract_dir, exist_ok=True)
            
            # Распаковываем архив
            if archive_type == 'zip':
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    zf.extractall(extract_dir)
            else:  # tar
                with tarfile.open(archive_path, 'r:*') as tf:
                    tf.extractall(extract_dir)
            
            logger.debug(f"📦 Extracted archive to: {extract_dir}")
            
            # Ищем plugin.json в распакованной папке
            plugin_json_path = os.path.join(extract_dir, "plugin.json")
            
            if not os.path.exists(plugin_json_path):
                logger.warning(f"⚠️ plugin.json not found in archive {os.path.basename(archive_path)}")
                return
            
            metadata = self._read_plugin_metadata(plugin_json_path)
            if not metadata:
                return
            
            # Ищем main.py в распакованной папке
            main_file = os.path.join(extract_dir, "main.py")
            if not os.path.exists(main_file):
                logger.warning(f"⚠️ main.py not found in archive {os.path.basename(archive_path)}")
                return
            
            await self._load_python_module_file(main_file, metadata)
            
        except Exception as e:
            logger.error(f"❌ Error loading archive {os.path.basename(archive_path)}: {e}", exc_info=True)
    
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
                logger.warning(f"⚠️ No InternalPluginBase subclass found in {os.path.basename(file_path)}")
                return
            
            # ========== DEPENDENCY INJECTION: MODELS ==========
            # Подготавливаем модели для передачи в плагин (чтобы плагин не импортировал их напрямую)
            models_dict = {
                'Device': Device,
                'PluginBinding': PluginBinding,
                'IntentMapping': IntentMapping,
                'Plugin': Plugin,
                'PluginVersion': PluginVersion,
            }
            
            # Создаём экземпляр плагина с передачей моделей
            plugin = plugin_class(self.app, self.db_session_maker, self.event_bus, models=models_dict)
            
            # Проверяем, включен ли плагин в БД (для плагинов, которые уже были загружены ранее)
            if not await self._is_plugin_enabled(plugin.id):
                logger.info(f"⏭️ Plugin {plugin.id} is disabled in DB, skipping load")
                return
            
            # Перезаписываем metadata из plugin.json если они есть
            if metadata.get('name'):
                plugin.name = metadata['name']
            if metadata.get('version'):
                plugin.version = metadata['version']
            if metadata.get('description'):
                plugin.description = metadata.get('description', '')
            
            # Сохраняем полный manifest в атрибут плагина для сохранения в БД
            plugin.manifest = metadata
            if metadata.get('type'):
                plugin.type = metadata['type']
            
            # Вызываем on_load с обработкой ошибок
            try:
                await plugin.on_load()
                plugin._is_loaded = True
            except Exception as e:
                logger.error(f"⚠️ Plugin on_load failed for {plugin.id}: {e}", exc_info=True)
                # Не продолжаем если on_load failed
                return
            
            # ========== SDK v0.0.2: AUTOMATIC ROUTER MOUNTING ==========
            # Используем встроенный метод mount_router() из SDK вместо ручной регистрации
            if plugin.router:
                try:
                    # Определяем prefix: инфраструктурные плагины (infrastructure=true в manifest) без префикса
                    is_infrastructure = (
                        metadata.get('infrastructure', False) or
                        getattr(plugin, 'infrastructure', False) or
                        metadata.get('type') == 'infrastructure'
                    )
                    
                    if is_infrastructure:
                        # Инфраструктурные плагины монтируются на /api без префикса плагина
                        custom_prefix = "/api"
                        logger.debug(f"  🏗️ Infrastructure plugin {plugin.id} mounted at {custom_prefix}")
                    else:
                        custom_prefix = f"/api/plugins/{plugin.id}"
                    
                    # Временно сохраняем prefix для mount_router
                    original_mount = plugin.mount_router
                    
                    async def custom_mount():
                        # Модифицируем mount_router для использования custom prefix
                        if plugin.router and not plugin._router_mounted:
                            before_app_routes = list(self.app.routes)
                            before_router_routes = None
                            if hasattr(self.app, 'router') and hasattr(self.app.router, 'routes'):
                                try:
                                    before_router_routes = list(self.app.router.routes)
                                except Exception:
                                    pass
                            
                            # Монтируем router
                            self.app.include_router(
                                plugin.router,
                                prefix=custom_prefix,
                                tags=[plugin.name]
                            )
                            plugin._router_mounted = True
                            logger.info(f"✅ Router mounted at {custom_prefix}")
                            
                            # Сохраняем добавленные routes для удаления
                            added_routes = []
                            try:
                                after_app_routes = list(self.app.routes)
                                for r in after_app_routes:
                                    if r not in before_app_routes:
                                        added_routes.append(r)
                            except Exception:
                                pass
                            
                            try:
                                if before_router_routes is not None and hasattr(self.app, 'router'):
                                    after_router_routes = list(self.app.router.routes)
                                    for r in after_router_routes:
                                        if r not in before_router_routes and r not in added_routes:
                                            added_routes.append(r)
                            except Exception:
                                pass
                            
                            # Сохраняем route objects
                            try:
                                async with self._lock:
                                    self.plugin_routes[plugin.id] = added_routes
                            except Exception:
                                self.plugin_routes[plugin.id] = added_routes
                            
                            # Force regenerate OpenAPI schema
                            try:
                                if hasattr(self.app, 'openapi_schema'):
                                    self.app.openapi_schema = None
                            except Exception:
                                pass
                    
                    # Вызываем модифицированный mount
                    await custom_mount()
                    
                except Exception as e:
                    logger.error(f"❌ Failed to mount router for {plugin.id}: {e}", exc_info=True)
                    # Не прерываем загрузку плагина
            else:
                logger.debug(f"  ℹ️ Plugin {plugin.id} has no router to mount")
            
            # Сохраняем в реестр
            try:
                async with self._lock:
                    self.plugins[plugin.id] = plugin
            except Exception:
                # Fallback if lock not initialized
                self.plugins[plugin.id] = plugin
            
            # Сохраняем информацию о плагине в БД
            await self._save_plugin_to_db(plugin)
            
            logger.info(f"✅ Loaded external plugin: {plugin.name} v{plugin.version}")
            
        except Exception as e:
            logger.error(f"❌ Failed to load module from {file_path}: {e}", exc_info=True)
    
    async def _update_plugin_loaded_status(self, plugin_id: str, loaded: bool):
        """
        Обновить статус загрузки плагина в БД.
        
        Args:
            plugin_id: ID плагина
            loaded: True если загружен, False если выгружен
        """
        try:
            async with get_session() as db:
                existing_q = await db.execute(select(Plugin).where(Plugin.id == plugin_id))
                existing = existing_q.scalar_one_or_none()
                
                if existing:
                    existing.loaded = loaded
                    await db.flush()
                    logger.debug(f"💾 Updated plugin {plugin_id} loaded status to {loaded}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to update plugin {plugin_id} loaded status: {e}")
    
    async def _save_plugin_to_db(self, plugin: InternalPluginBase):
        """
        Сохранить информацию о плагине в базу данных.
        
        Args:
            plugin: Экземпляр загруженного плагина
        """
        try:
            async with get_session() as db:
                # Проверяем, существует ли плагин в БД
                existing_q = await db.execute(select(Plugin).where(Plugin.id == plugin.id))
                existing = existing_q.scalar_one_or_none()
                
                # Получаем manifest если есть
                manifest = None
                if hasattr(plugin, 'manifest'):
                    manifest = plugin.manifest
                elif hasattr(plugin, '_manifest'):
                    manifest = plugin._manifest

                # Получаем type если есть
                plugin_type = None
                if hasattr(plugin, 'type'):
                    plugin_type = plugin.type
                elif hasattr(plugin, '_type'):
                    plugin_type = plugin._type

                # Определяем режим работы плагина из manifest или типа
                runtime_mode = None
                supported_modes = None
                mode_switch_supported = False
                
                if manifest:
                    runtime_mode = manifest.get('runtime_mode')
                    supported_modes = manifest.get('supported_modes')
                    mode_switch_supported = manifest.get('mode_switch_supported', False)
                    
                if not runtime_mode:
                    # Определяем по типу плагина
                    if plugin_type == 'external':
                        runtime_mode = 'microservice'
                    elif plugin_type == 'internal':
                        runtime_mode = 'in_process'
                    else:
                        runtime_mode = 'in_process'  # По умолчанию
                
                # Если supported_modes не указан, определяем по типу
                if not supported_modes:
                    if plugin_type == 'external':
                        supported_modes = ['microservice']
                    elif plugin_type == 'internal':
                        supported_modes = ['in_process']
                    else:
                        supported_modes = [runtime_mode]
                
                # Конфигурация плагина если есть
                plugin_config = getattr(plugin, 'config', None)

                # Преобразуем PluginConfig или другие нестандартные объекты в JSON-сериализуемую структуру
                def _to_serializable(obj):
                    if obj is None:
                        return None
                    # Простые типы оставляем как есть
                    if isinstance(obj, (dict, list, str, int, float, bool)):
                        return obj
                    # Попробуем pydantic-like to_dict
                    if hasattr(obj, 'dict') and callable(getattr(obj, 'dict')):
                        try:
                            return obj.dict()
                        except Exception:
                            pass
                    # Если это обёртка PluginConfig — возьмём plugin_id и кеш
                    if hasattr(obj, 'plugin_id'):
                        result = {'plugin_id': getattr(obj, 'plugin_id')}
                        if hasattr(obj, '_config_cache'):
                            try:
                                result['cache'] = dict(getattr(obj, '_config_cache') or {})
                            except Exception:
                                result['cache'] = str(getattr(obj, '_config_cache'))
                        return result
                    # Если есть __dict__, возьмём его (фильтруя приватные и несериализуемые значения)
                    if hasattr(obj, '__dict__'):
                        out = {}
                        for k, v in vars(obj).items():
                            if k.startswith('__'):
                                continue
                            try:
                                json.dumps(v)
                                out[k] = v
                            except Exception:
                                out[k] = str(v)
                        return out
                    # Фоллбек — str()
                    return str(obj)

                plugin_config_serializable = _to_serializable(plugin_config)
                
                # Создаем или обновляем запись Plugin
                if not existing:
                    plugin_obj = Plugin(
                        id=plugin.id,
                        name=plugin.name or plugin.id,
                        description=getattr(plugin, 'description', None),
                        publisher=None,
                        latest_version=getattr(plugin, 'version', None),
                        enabled=True,  # при первой загрузке считаем разрешенным
                        loaded=True,   # Плагин только что загружен
                        runtime_mode=runtime_mode,
                        supported_modes=supported_modes,
                        mode_switch_supported=mode_switch_supported,
                        config=plugin_config_serializable
                    )
                    db.add(plugin_obj)
                    await db.flush()
                    logger.debug(f"💾 Created Plugin record in DB: {plugin.id} (mode: {runtime_mode}, supported: {supported_modes})")
                else:
                    # Обновляем существующую запись
                    if plugin.name:
                        existing.name = plugin.name
                    if hasattr(plugin, 'description') and plugin.description:
                        existing.description = plugin.description
                    if hasattr(plugin, 'version') and plugin.version:
                        existing.latest_version = plugin.version
                    # Разрешаем к загрузке при успешной загрузке
                    if hasattr(existing, 'enabled'):
                        existing.enabled = True
                    existing.loaded = True  # Плагин загружен
                    if runtime_mode:
                        existing.runtime_mode = runtime_mode
                    if supported_modes:
                        existing.supported_modes = supported_modes
                    existing.mode_switch_supported = mode_switch_supported
                    if plugin_config is not None:
                        existing.config = plugin_config_serializable
                    await db.flush()
                    logger.debug(f"💾 Updated Plugin record in DB: {plugin.id} (mode: {runtime_mode}, supported: {supported_modes})")
                
                # Создаем или обновляем запись PluginVersion
                version = getattr(plugin, 'version', None) or 'unknown'
                pv_id = f"{plugin.id}:{version}"

                pv = PluginVersion(
                    id=pv_id,
                    plugin_name=plugin.id,
                    version=version,
                    manifest=manifest,
                    artifact_url=None,
                    type=plugin_type
                )
                await db.merge(pv)
                await db.flush()
                logger.debug(f"💾 Saved PluginVersion record in DB: {pv_id}")
                
        except Exception as e:
            # Не прерываем загрузку плагина, если не удалось сохранить в БД
            logger.warning(f"⚠️ Failed to save plugin {plugin.id} to DB: {e}", exc_info=True)
    
    def _read_plugin_metadata(self, plugin_json_path: str) -> Optional[Dict[str, Any]]:
        """
        Прочитать метаданные плагина из plugin.json.
        
        Args:
            plugin_json_path: Путь к файлу plugin.json
            
        Returns:
            Dict с метаданными или None если ошибка
        """
        try:
            with open(plugin_json_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            # Проверяем обязательные поля
            required_fields = ['id', 'name', 'version']
            for field in required_fields:
                if field not in metadata:
                    logger.warning(f"⚠️ Missing required field '{field}' in {plugin_json_path}")
                    return None
            
            logger.debug(f"✅ Read plugin metadata: {metadata['id']}")
            return metadata
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON in {plugin_json_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Error reading {plugin_json_path}: {e}")
            return None
    
    async def _is_plugin_enabled(self, plugin_id: str) -> bool:
        """
        Проверить, включен ли плагин (loaded=True в БД).
        
        Args:
            plugin_id: ID плагина
            
        Returns:
            True если плагин включен, False если отключен или не найден
        """
        try:
            async with get_session() as db:
                existing_q = await db.execute(select(Plugin).where(Plugin.id == plugin_id))
                existing = existing_q.scalar_one_or_none()
                
                if existing:
                    # Если плагин есть в БД, проверяем флаг enabled (если нет - используем loaded)
                    if hasattr(existing, 'enabled'):
                        return bool(getattr(existing, 'enabled', True))
                    return getattr(existing, 'loaded', True)
                else:
                    # Если плагина нет в БД, считаем его включенным (первая загрузка)
                    return True
        except Exception as e:
            logger.warning(f"⚠️ Failed to check plugin {plugin_id} status: {e}")
            # В случае ошибки считаем плагин включенным
            return True
    
    async def load_plugin(self, module_name: str, plugin_type: str = "builtin"):
        """
        Загрузить встроенный плагин из модуля.
        
        Ищет в модуле класс, наследующий InternalPluginBase, и инициализирует его.
        
        Args:
            module_name: Полное имя модуля (например: "plugins.devices_plugin")
            plugin_type: "builtin" или "external"
        """
        try:
            logger.debug(f"Loading {plugin_type} plugin from module: {module_name}")
            
            # Импортируем модуль
            # Примечание: для встроенных плагинов зависимости проверяются в _load_builtin_plugins перед вызовом load_plugin
            module = importlib.import_module(module_name)
            
            # Ищем класс плагина (наследник InternalPluginBase)
            plugin_class = None
            
            # Сначала проверяем, есть ли класс в __all__ или экспортирован напрямую
            if hasattr(module, '__all__'):
                for attr_name in module.__all__:
                    attr = getattr(module, attr_name, None)
                    if (isinstance(attr, type) and 
                        issubclass(attr, InternalPluginBase) and 
                        attr is not InternalPluginBase):
                        plugin_class = attr
                        break
            
            # Если не нашли, ищем во всех атрибутах модуля
            if not plugin_class:
                for attr_name in dir(module):
                    if attr_name.startswith('_'):
                        continue
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and 
                        issubclass(attr, InternalPluginBase) and 
                        attr is not InternalPluginBase):
                        plugin_class = attr
                        break
            
            if not plugin_class:
                logger.warning(f"⚠️ No InternalPluginBase subclass found in {module_name}")
                return
            
            # ========== DEPENDENCY INJECTION: MODELS ==========
            # Подготавливаем модели для передачи в плагин
            models_dict = {
                'Device': Device,
                'PluginBinding': PluginBinding,
                'IntentMapping': IntentMapping,
                'Plugin': Plugin,
                'PluginVersion': PluginVersion,
            }
            
            # Создаём экземпляр плагина с передачей моделей
            plugin = plugin_class(self.app, self.db_session_maker, self.event_bus, models=models_dict)
            
            # Проверяем, включен ли плагин в БД (для плагинов, которые уже были загружены ранее)
            if not await self._is_plugin_enabled(plugin.id):
                logger.info(f"⏭️ Plugin {plugin.id} is disabled in DB, skipping load")
                return

            # Подтягиваем сохраненную конфигурацию из БД и прокидываем в экземпляр плагина
            # Также добавляем глобальные настройки из PluginConfigManager
            try:
                # Получаем глобальную конфигурацию из PluginConfigManager если доступен
                global_config = {}
                if hasattr(self.app.state, 'plugin_config_manager'):
                    try:
                        config_manager = self.app.state.plugin_config_manager
                        plugin_config = await config_manager.get_config(plugin.id)
                        if plugin_config:
                            # Добавляем глобальные настройки устройств в config плагина
                            global_config = {
                                'device_online_timeout': plugin_config.device_online_timeout,
                                'device_poll_interval': plugin_config.device_poll_interval
                            }
                            logger.debug(f"📋 Global device settings for {plugin.id}: online_timeout={plugin_config.device_online_timeout}s, poll_interval={plugin_config.device_poll_interval}s")
                    except Exception as e:
                        logger.debug(f"Could not get global config for {plugin.id}: {e}")
                
                async with get_session() as db:
                    existing_q = await db.execute(select(Plugin).where(Plugin.id == plugin.id))
                    existing = existing_q.scalar_one_or_none()
                    
                    # Инициализируем base_cfg перед использованием
                    base_cfg = getattr(plugin, "config", None) or {}
                    # Если base_cfg — не mapping (например, PluginConfig), попытаемся привести к dict
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
                        # existing.config может быть dict/JSONB
                        persisted = existing.config if isinstance(existing.config, dict) else {}
                        # Мержим: base_cfg -> persisted -> global_config (глобальные настройки имеют приоритет)
                        merged = {**base_cfg, **persisted, **global_config}
                        logger.info(f"🔧 Applied persisted config for plugin {plugin.id}: {persisted}")
                    else:
                        # Мержим базовую конфигурацию с глобальными настройками
                        merged = {**base_cfg, **global_config}
                        logger.info(f"ℹ️ No persisted config found for plugin {plugin.id}, using defaults + global settings")
                    
                    # Обновляем конфигурацию плагина
                    # Если plugin.config это объект PluginConfig, обновляем его внутренний словарь
                    if hasattr(plugin.config, 'config') and isinstance(plugin.config.config, dict):
                        plugin.config.config.update(merged)
                    else:
                        # Иначе создаем словарь для доступа через config.get()
                        plugin.config = merged
            except Exception as e:
                logger.warning(f"⚠️ Failed to apply persisted config for plugin {plugin.id}: {e}")
            
            # Пытаемся загрузить manifest.json для встроенных плагинов
            if plugin_type == "builtin" and hasattr(module, '__file__'):
                module_file = module.__file__
                if module_file:
                    # Ищем manifest.json в папке модуля
                    module_dir = os.path.dirname(module_file)
                    manifest_path = os.path.join(module_dir, "manifest.json")
                    if os.path.exists(manifest_path):
                        try:
                            manifest_data = self._read_plugin_metadata(manifest_path)
                            if manifest_data:
                                plugin.manifest = manifest_data
                                if manifest_data.get('type'):
                                    plugin.type = manifest_data['type']
                                logger.debug(f"📋 Loaded manifest.json for {plugin.id}")
                        except Exception as e:
                            logger.debug(f"⚠️ Failed to load manifest.json for {plugin.id}: {e}")
            
            # Вызываем on_load
            try:
                await plugin.on_load()
                plugin._is_loaded = True
            except Exception as e:
                logger.error(f"⚠️ Plugin on_load failed for {plugin.id}: {e}", exc_info=True)
                # Не продолжаем если on_load failed
                return
            
            # ========== SDK v0.0.2: AUTOMATIC ROUTER MOUNTING ==========
            # Используем встроенный метод mount_router() из SDK вместо ручной регистрации
            if plugin.router:
                try:
                    # Определяем prefix: инфраструктурные плагины (infrastructure=true в manifest) без префикса
                    manifest = getattr(plugin, 'manifest', None) or {}
                    is_infrastructure = (
                        manifest.get('infrastructure', False) or
                        getattr(plugin, 'infrastructure', False) or
                        manifest.get('type') == 'infrastructure'
                    )
                    
                    if is_infrastructure:
                        # Инфраструктурные плагины монтируются на /api без префикса плагина
                        custom_prefix = "/api"
                        logger.debug(f"  🏗️ Infrastructure plugin {plugin.id} mounted at {custom_prefix}")
                    else:
                        custom_prefix = f"/api/plugins/{plugin.id}"
                    
                    # Модифицируем mount_router для использования custom prefix
                    async def custom_mount():
                        if plugin.router and not plugin._router_mounted:
                            before_app_routes = list(self.app.routes)
                            before_router_routes = None
                            if hasattr(self.app, 'router') and hasattr(self.app.router, 'routes'):
                                try:
                                    before_router_routes = list(self.app.router.routes)
                                except Exception:
                                    pass
                            
                            # Монтируем router
                            self.app.include_router(
                                plugin.router,
                                prefix=custom_prefix,
                                tags=[plugin.name]
                            )
                            plugin._router_mounted = True
                            logger.info(f"✅ Router mounted at {custom_prefix}")
                            
                            # Сохраняем добавленные routes для удаления
                            added_routes = []
                            try:
                                after_app_routes = list(self.app.routes)
                                for r in after_app_routes:
                                    if r not in before_app_routes:
                                        added_routes.append(r)
                            except Exception:
                                pass
                            
                            try:
                                if before_router_routes is not None and hasattr(self.app, 'router'):
                                    after_router_routes = list(self.app.router.routes)
                                    for r in after_router_routes:
                                        if r not in before_router_routes and r not in added_routes:
                                            added_routes.append(r)
                            except Exception:
                                pass
                            
                            # Сохраняем route objects
                            try:
                                async with self._lock:
                                    self.plugin_routes[plugin.id] = added_routes
                            except Exception:
                                self.plugin_routes[plugin.id] = added_routes
                            
                            # Force regenerate OpenAPI schema
                            try:
                                if hasattr(self.app, 'openapi_schema'):
                                    self.app.openapi_schema = None
                            except Exception:
                                pass
                    
                    # Вызываем модифицированный mount
                    await custom_mount()
                    
                except Exception as e:
                    logger.error(f"❌ Failed to mount router for {plugin.id}: {e}", exc_info=True)
                    # Не прерываем загрузку плагина
            else:
                logger.debug(f"  ℹ️ Plugin {plugin.id} has no router to mount")
            
            # Сохраняем в реестр
            try:
                async with self._lock:
                    self.plugins[plugin.id] = plugin
            except Exception:
                self.plugins[plugin.id] = plugin
            
            # Сохраняем информацию о плагине в БД
            await self._save_plugin_to_db(plugin)
            
            logger.info(f"✅ Loaded {plugin_type} plugin: {plugin.name} v{plugin.version}")
            
        except Exception as e:
            logger.error(
                f"❌ Failed to load {plugin_type} plugin from {module_name}: {e}",
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
            # Получаем сохранённые данные о роутерах/префиксе плагина
            saved = self.plugin_routes.get(plugin_id)

            removed_count = 0
            # Если мы ранее сохранили список route-объектов, удаляем именно их
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

                # Очищаем сохранённые данные
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

            # Если сохранено как префикс (устаревший формат), использовать прежнюю логику
            elif isinstance(saved, str) and saved:
                prefix = saved
                # Safety: do not remove core application routes mounted at "/api"
                if prefix == "/api":
                    logger.info(f"⚠️ Skipping route removal for infrastructure prefix {prefix}")
                    routes_to_remove = []
                else:
                    routes_to_remove = []

                # Проверяем app.routes (основной список роутов)
                for route in list(self.app.routes):
                    route_path = getattr(route, 'path', '')
                    if route_path and route_path.startswith(prefix):
                        routes_to_remove.append(route)
                        logger.debug(f"  🗑️ Found route to remove: {route_path}")

                # Также проверяем app.router.routes (роутеры могут быть вложены)
                if hasattr(self.app, 'router') and hasattr(self.app.router, 'routes'):
                    for route in list(self.app.router.routes):
                        route_path = getattr(route, 'path', '')
                        if route_path and route_path.startswith(prefix):
                            if route not in routes_to_remove:
                                routes_to_remove.append(route)
                                logger.debug(f"  🗑️ Found route in router.routes: {route_path}")

                for route in routes_to_remove:
                    try:
                        if route in self.app.routes:
                            self.app.routes.remove(route)
                            removed_count += 1
                            logger.debug(f"  ✅ Removed route from app.routes: {getattr(route, 'path', 'unknown')}")
                        elif hasattr(self.app, 'router') and hasattr(self.app.router, 'routes') and route in self.app.router.routes:
                            self.app.router.routes.remove(route)
                            removed_count += 1
                            logger.debug(f"  ✅ Removed route from router.routes: {getattr(route, 'path', 'unknown')}")
                    except (ValueError, AttributeError) as e:
                        logger.debug(f"  ⚠️ Could not remove route {getattr(route, 'path', 'unknown')}: {e}")

                if removed_count == 0:
                    logger.warning(f"⚠️ No routes found to remove for prefix {prefix}")
                else:
                    logger.info(f"🗑️ Removed {removed_count} route(s) for plugin {plugin_id}")

                try:
                    async with self._lock:
                        if plugin_id in self.plugin_routes:
                            del self.plugin_routes[plugin_id]
                except Exception:
                    if plugin_id in self.plugin_routes:
                        del self.plugin_routes[plugin_id]

                if hasattr(self.app, 'openapi_schema'):
                    self.app.openapi_schema = None
                    logger.debug(f"  🔄 Cleared OpenAPI schema cache for Swagger update")

            else:
                logger.warning(f"⚠️ No route info found for plugin {plugin_id}, routes may not be removed")
            
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
            await self._update_plugin_loaded_status(plugin_id, loaded=False)
            
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
                "loaded": True  # runtime список — значит загружен
            }
            for p in self.plugins.values()
        ]
    
    async def install_from_url(self, url: str) -> Dict[str, Any]:
        """
        Установить плагин из URL (zip/tar.gz файл).
        
        Args:
            url: URL к архиву плагина
            
        Returns:
            Dict с результатом установки
        """
        import httpx
        
        if not self.external_plugins_dir:
            raise ValueError("PLUGINS_DIR not configured")
        
        os.makedirs(self.external_plugins_dir, exist_ok=True)
        
        logger.info(f"📥 Downloading plugin from {url}")
        
        try:
            # Download file
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()
            
            # Determine file type from URL or content-type
            filename = url.split('/')[-1].split('?')[0]
            if not filename.endswith(('.zip', '.tar.gz', '.tgz')):
                content_type = response.headers.get('content-type', '')
                if 'zip' in content_type:
                    filename += '.zip'
                else:
                    filename += '.tar.gz'
            
            # Save to temp file
            temp_path = os.path.join(tempfile.gettempdir(), filename)
            with open(temp_path, 'wb') as f:
                f.write(response.content)
            
            # Extract to plugins dir and capture any newly loaded plugin ids
            before = set(self.plugins.keys())
            if filename.endswith('.zip'):
                await self._load_external_archive(temp_path, 'zip')
            else:
                await self._load_external_archive(temp_path, 'tar')
            after = set(self.plugins.keys())
            new = list(after - before)
            
            # Install dependencies for newly loaded plugins
            deps_results = {}
            for plugin_id in new:
                plugin_path = os.path.join(self.external_plugins_dir, plugin_id)
                if os.path.isdir(plugin_path):
                    deps_result = await asyncio.to_thread(self._install_plugin_dependencies, plugin_path, plugin_id)
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
        """
        Установить плагин из локального файла/папки.
        
        Args:
            path: Путь к файлу или папке плагина
            
        Returns:
            Dict с результатом установки
        """
        if not os.path.exists(path):
            raise FileNotFoundError(f'Plugin path not found: {path}')
        
        if not self.external_plugins_dir:
            raise ValueError('PLUGINS_DIR not configured')
        
        os.makedirs(self.external_plugins_dir, exist_ok=True)
        
        logger.info(f'📁 Installing plugin from {path}')
        
        try:
            if os.path.isdir(path):
                # Copy directory
                plugin_name = os.path.basename(path)
                dest_path = os.path.join(self.external_plugins_dir, plugin_name)
                
                if os.path.exists(dest_path):
                    shutil.rmtree(dest_path)
                
                before = set(self.plugins.keys())
                shutil.copytree(path, dest_path)
                
                # Install dependencies
                deps_result = await asyncio.to_thread(self._install_plugin_dependencies, dest_path, plugin_name)
                
                await self._load_external_package(dest_path, plugin_name)
                after = set(self.plugins.keys())
                new = list(after - before)
                
            elif path.endswith('.py'):
                # Copy Python file
                filename = os.path.basename(path)
                dest_path = os.path.join(self.external_plugins_dir, filename)
                before = set(self.plugins.keys())
                shutil.copy2(path, dest_path)
                await self._load_external_python_file(dest_path)
                after = set(self.plugins.keys())
                new = list(after - before)
                
            elif path.endswith('.zip'):
                before = set(self.plugins.keys())
                await self._load_external_archive(path, 'zip')
                after = set(self.plugins.keys())
                new = list(after - before)
                
            elif path.endswith(('.tar.gz', '.tgz')):
                before = set(self.plugins.keys())
                await self._load_external_archive(path, 'tar')
                after = set(self.plugins.keys())
                new = list(after - before)
            else:
                raise ValueError(f'Unsupported file type: {path}')
            
            logger.info(f'✅ Plugin installed from {path}')
            res: Dict[str, Any] = {'status': 'installed', 'source': path}
            if 'new' in locals() and new:
                res['plugin_ids'] = new
                if len(new) == 1:
                    res['plugin_id'] = new[0]
            return res
            
        except Exception as e:
            logger.error(f'❌ Failed to install plugin from local path: {e}', exc_info=True)
            raise

    def _install_plugin_dependencies(self, plugin_path: str, plugin_id: str) -> Dict[str, Any]:
        """
        Установить зависимости плагина из requirements.txt.
        
        Args:
            plugin_path: Путь к директории плагина
            plugin_id: ID плагина
            
        Returns:
            Dict с результатом установки зависимостей
        """
        requirements_file = os.path.join(plugin_path, 'requirements.txt')
        
        if not os.path.exists(requirements_file):
            logger.debug(f"ℹ️ No requirements.txt found for plugin {plugin_id}")
            return {'status': 'skipped', 'reason': 'no_requirements'}
        
        try:
            logger.info(f"📦 Installing dependencies for plugin {plugin_id}")
            
            # Определяем, нужно ли использовать --user
            # В Docker контейнере или при работе от root можно устанавливать в системный site-packages
            use_user_flag = True
            if os.path.exists('/.dockerenv') or os.getenv('DOCKER_CONTAINER'):
                # В Docker контейнере обычно работаем от root, можно без --user
                use_user_flag = False
                logger.debug("🐳 Running in Docker, installing to system site-packages")
            elif os.geteuid() == 0:
                # Работаем от root, можно без --user
                use_user_flag = False
                logger.debug("🔑 Running as root, installing to system site-packages")
            
            # Формируем команду pip
            pip_cmd = [sys.executable, '-m', 'pip', 'install', '-r', requirements_file, '--no-warn-script-location', '--no-cache-dir']
            if use_user_flag:
                pip_cmd.append('--user')
            
            result = subprocess.run(
                pip_cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 минут таймаут
            )
            
            if result.returncode == 0:
                # Добавляем путь к user site-packages в sys.path только если использовали --user
                # Это нужно, чтобы Python мог найти только что установленные пакеты
                if use_user_flag:
                    try:
                        user_site = site.getusersitepackages()
                        if user_site and os.path.exists(user_site):
                            if user_site not in sys.path:
                                sys.path.insert(0, user_site)
                                logger.debug(f"📦 Added user site-packages to sys.path: {user_site}")
                            
                            # Также пробуем добавить через site.addsitedir для правильной инициализации
                            site.addsitedir(user_site)
                            logger.debug(f"📦 Initialized user site-packages: {user_site}")
                    except Exception as e:
                        logger.debug(f"Could not add user site-packages to sys.path: {e}")
                else:
                    # При установке в системный site-packages просто перезагружаем site
                    # чтобы Python увидел новые пакеты
                    try:
                        import importlib
                        importlib.reload(site)
                        logger.debug("📦 Reloaded site module to detect new packages")
                    except Exception as e:
                        logger.debug(f"Could not reload site module: {e}")
                
                # Проверяем, что пакеты действительно установились
                if result.stdout:
                    logger.debug(f"📦 Pip output: {result.stdout[:500]}")  # Первые 500 символов
                
                logger.info(f"✅ Dependencies installed for plugin {plugin_id}")
                return {'status': 'installed', 'output': result.stdout}
            else:
                logger.error(f"❌ Failed to install dependencies for plugin {plugin_id}: {result.stderr}")
                if result.stdout:
                    logger.debug(f"📦 Pip stdout: {result.stdout[:500]}")
                return {'status': 'failed', 'error': result.stderr}
                
        except subprocess.TimeoutExpired:
            logger.error(f"❌ Dependency installation timeout for plugin {plugin_id}")
            return {'status': 'failed', 'error': 'timeout'}
        except Exception as e:
            logger.error(f"❌ Error installing dependencies for plugin {plugin_id}: {e}", exc_info=True)
            return {'status': 'failed', 'error': str(e)}

    def install_from_git(self, git_url: str) -> Dict[str, Any]:
        """
        Синхронная установка плагина из git-репозитория.

        Этот метод выполняет `git clone` в временную папку, ищет `plugin.json`,
        копирует содержимое в `PLUGINS_DIR` и пытается загрузить плагин.

        Вызывается через `asyncio.to_thread(...)` в маршрутах.
        """
        if not self.external_plugins_dir:
            raise ValueError('PLUGINS_DIR not configured')

        os.makedirs(self.external_plugins_dir, exist_ok=True)

        tmp_clone = tempfile.mkdtemp(prefix='plugin_clone_')
        try:
            logger.info(f"📥 Cloning plugin from git {git_url}")
            subprocess.check_call(["git", "clone", "--depth", "1", git_url, tmp_clone])

            # Найти plugin.json — может быть в корне или в единственной вложенной папке
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

            with open(plugin_json, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            plugin_id = metadata.get('id') or os.path.basename(git_url).replace('.git', '')
            dest_path = os.path.join(self.external_plugins_dir, plugin_id)

            if os.path.exists(dest_path):
                shutil.rmtree(dest_path)

            shutil.copytree(plugin_root, dest_path)
            
            # Устанавливаем зависимости плагина
            deps_result = self._install_plugin_dependencies(dest_path, plugin_id)

            # Загружаем плагин — запускаем корутину в новом цикле событий в этом потоке
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
    
    async def _get_plugin_runtime_mode(self, plugin_id: str) -> str:
        """
        Получить режим работы плагина.
        
        Args:
            plugin_id: ID плагина
            
        Returns:
            Режим работы: "in-process", "microservice", "hybrid" или "in-process" по умолчанию
        """
        try:
            async with get_session() as db:
                existing_q = await db.execute(select(Plugin).where(Plugin.id == plugin_id))
                existing = existing_q.scalar_one_or_none()
                
                if existing and hasattr(existing, 'runtime_mode') and existing.runtime_mode:
                    return existing.runtime_mode
                
                # Проверяем метаданные плагина
                if plugin_id in self.plugins:
                    plugin = self.plugins[plugin_id]
                    if hasattr(plugin, 'manifest') and plugin.manifest:
                        runtime_mode = plugin.manifest.get('runtime_mode')
                        if runtime_mode:
                            return runtime_mode
                    # Проверяем тип плагина
                    if hasattr(plugin, 'type'):
                        plugin_type = plugin.type
                        if plugin_type == 'external':
                            return 'microservice'
                        elif plugin_type == 'internal':
                            return 'in_process'
                
                # По умолчанию - in_process
                return 'in_process'
        except Exception as e:
            logger.debug(f"⚠️ Failed to get runtime mode for plugin {plugin_id}: {e}")
            return 'in-process'
    
    async def _get_plugin_tables(self, plugin_id: str) -> List[str]:
        """
        Получить список таблиц, принадлежащих плагину.
        
        Args:
            plugin_id: ID плагина
            
        Returns:
            Список имен таблиц плагина
        """
        # Маппинг известных плагинов и их таблиц
        plugin_tables_map = {
            'client_manager': ['clients', 'command_logs', 'enrollments', 'terminal_audit'],
            # Добавьте другие плагины по мере необходимости
        }
        
        return plugin_tables_map.get(plugin_id, [])
    
    async def _drop_plugin_tables(self, plugin_id: str, drop_data: bool = False) -> List[str]:
        """
        Удалить таблицы плагина из БД.
        
        Args:
            plugin_id: ID плагина
            drop_data: Если True, удаляет таблицы с данными. Если False, только логирует предупреждение.
            
        Returns:
            Список удаленных таблиц
        """
        # Проверяем режим работы плагина
        runtime_mode = await self._get_plugin_runtime_mode(plugin_id)
        
        # Для microservice плагинов НЕ удаляем таблицы (они в своей БД)
        if runtime_mode == 'microservice':
            logger.info(
                f"ℹ️ Plugin {plugin_id} runs in microservice mode. "
                f"Tables are managed by the plugin service itself, not dropping."
            )
            return []
        
        tables = await self._get_plugin_tables(plugin_id)
        
        if not tables:
            logger.debug(f"ℹ️ No tables found for plugin {plugin_id}")
            return []
        
        if not drop_data:
            logger.warning(
                f"⚠️ Plugin {plugin_id} has tables in DB: {', '.join(tables)}. "
                f"Tables are NOT dropped to preserve data. "
                f"To drop tables, use uninstall with drop_tables=True"
            )
            return []
        
        dropped_tables = []
        try:
            from sqlalchemy import text
            from .db import engine
            
            async with engine.begin() as conn:
                # Пытаемся удалить каждую таблицу
                # DROP TABLE IF EXISTS безопасен - не вызовет ошибку, если таблицы нет
                for table_name in tables:
                    try:
                        # Используем IF EXISTS для безопасности
                        await conn.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))
                        dropped_tables.append(table_name)
                        logger.info(f"🗑️ Dropped table: {table_name}")
                    except Exception as e:
                        logger.debug(f"ℹ️ Could not drop table {table_name}: {e}")
            
            if dropped_tables:
                logger.info(f"✅ Dropped {len(dropped_tables)} table(s) for plugin {plugin_id}")
            else:
                logger.debug(f"ℹ️ No tables were dropped for plugin {plugin_id}")
        except Exception as e:
            logger.error(f"❌ Failed to drop tables for plugin {plugin_id}: {e}", exc_info=True)
            # Не прерываем процесс удаления плагина из-за ошибки удаления таблиц
        
        return dropped_tables
    
    async def uninstall_plugin(self, plugin_id: str, drop_tables: bool = False) -> Dict[str, Any]:
        """
        Удалить плагин (из файловой системы).
        
        Args:
            plugin_id: ID плагина
            drop_tables: Если True, удаляет таблицы плагина из БД (ОПАСНО - удаляет данные!)
            
        Returns:
            Dict с результатом удаления
        """
        if not self.external_plugins_dir:
            raise ValueError('PLUGINS_DIR not configured. Cannot uninstall builtin plugins.')
        
        logger.info(f'🗑️ Uninstalling plugin {plugin_id}')
        
        # Сначала выгружаем плагин, если он загружен
        if plugin_id in self.plugins:
            await self.unload_plugin(plugin_id)
        
        # Удаляем таблицы, если запрошено
        dropped_tables = []
        if drop_tables:
            dropped_tables = await self._drop_plugin_tables(plugin_id, drop_data=True)
        
        # Find plugin directory
        plugin_path = os.path.join(self.external_plugins_dir, plugin_id)
        
        if not os.path.exists(plugin_path):
            # Try to find by scanning all plugins
            for item in os.listdir(self.external_plugins_dir):
                item_path = os.path.join(self.external_plugins_dir, item)
                plugin_json = os.path.join(item_path, 'plugin.json')
                
                if os.path.exists(plugin_json):
                    try:
                        with open(plugin_json, 'r') as f:
                            metadata = json.load(f)
                        if metadata.get('id') == plugin_id:
                            plugin_path = item_path
                            break
                    except Exception:
                        continue
        
        if not os.path.exists(plugin_path):
            raise FileNotFoundError(f'Plugin directory not found: {plugin_id}')
        
        try:
            if os.path.isdir(plugin_path):
                shutil.rmtree(plugin_path)
            else:
                os.remove(plugin_path)
            
            result = {'status': 'uninstalled', 'plugin_id': plugin_id}
            if dropped_tables:
                result['dropped_tables'] = dropped_tables
            elif await self._get_plugin_tables(plugin_id):
                result['warning'] = f"Plugin tables remain in DB. Use drop_tables=True to remove them."
            
            logger.info(f'✅ Plugin {plugin_id} uninstalled')
            return result
            
        except Exception as e:
            logger.error(f'❌ Failed to uninstall plugin: {e}', exc_info=True)
            raise
    
    async def reload_plugin(self, plugin_id: str) -> Dict[str, Any]:
        """
        Перезагрузить плагин.
        
        Args:
            plugin_id: ID плагина
            
        Returns:
            Dict с результатом перезагрузки
        """
        logger.info(f'🔄 Reloading plugin {plugin_id}')
        
        # Find the plugin module
        module_name = None
        
        # Check if it's a builtin plugin
        try:
            import core_service.plugins as plugins_package
            package_name = 'core_service.plugins'
        except ImportError:
            try:
                import plugins as plugins_package
                package_name = 'plugins'
            except ImportError:
                plugins_package = None
                package_name = None
        
        if plugins_package:
            plugin_modules = list(pkgutil.walk_packages(
                plugins_package.__path__,
                prefix=package_name + '.'
            ))
            
            logger.info(f"🔍 Found {len(plugin_modules)} modules in plugins package")
            
            for _, mod_name, _ in plugin_modules:
                # Match by exact id (package name or module name)
                parts = mod_name.split('.')
                last_part = parts[-1]
                second_last = parts[-2] if len(parts) > 1 else ''
                
                # Skip helper modules (embed, models, etc.)
                if last_part in ('embed', 'models', 'utils', 'base'):
                    continue
                
                if last_part == plugin_id or second_last == plugin_id:
                    module_name = mod_name
                    logger.debug(f"Matched module {mod_name} for plugin {plugin_id}")
                    break
            
            # If not found yet, try checking plugin_id as package
            if not module_name:
                potential_package = f"{package_name}.{plugin_id}"
                logger.debug(f"Trying to import {potential_package}")
                try:
                    importlib.import_module(potential_package)
                    module_name = potential_package
                    logger.debug(f"Successfully imported {potential_package}")
                except ImportError as ie:
                    logger.debug(f"Failed to import {potential_package}: {ie}")
        
        if module_name:
            # If plugin is already loaded, unload first to avoid duplicate routes/instances
            if plugin_id in self.plugins:
                try:
                    await self.unload_plugin(plugin_id)
                except Exception as e:
                    logger.debug(f"⚠️ Failed to unload before reload: {e}")

            # Reload builtin plugin
            await self.load_plugin(module_name, plugin_type='builtin')
            logger.info(f'✅ Reloaded builtin plugin {plugin_id}')
            return {'status': 'reloaded', 'plugin_id': plugin_id, 'type': 'builtin'}
        
        # Try external plugins
        if self.external_plugins_dir:
            # If plugin is already loaded, unload first
            if plugin_id in self.plugins:
                try:
                    await self.unload_plugin(plugin_id)
                except Exception as e:
                    logger.debug(f"⚠️ Failed to unload before reload (external): {e}")

            await self._load_external_plugins()

            if plugin_id in self.plugins:
                logger.info(f'✅ Reloaded external plugin {plugin_id}')
                return {'status': 'reloaded', 'plugin_id': plugin_id, 'type': 'external'}
        
        raise ValueError(f'Plugin {plugin_id} not found')
    
    def __del__(self):
        """Cleanup temp directory on destruction."""
        try:
            if hasattr(self, 'temp_dir') and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass

