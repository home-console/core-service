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
from pathlib import Path
from typing import Dict, List, Optional, Any
from .plugin_base import InternalPluginBase
from .event_bus import event_bus

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
        
        # Директория с внешними плагинами (из переменной окружения)
        self.external_plugins_dir = os.getenv("PLUGINS_DIR")
        
        # Временная директория для распакованных архивов
        self.temp_dir = tempfile.mkdtemp(prefix="plugins_")
        
        logger.info(f"🔌 PluginLoader initialized")
        if self.external_plugins_dir:
            logger.info(f"📂 External plugins directory: {self.external_plugins_dir}")
        else:
            logger.info(f"📂 No external plugins directory set (PLUGINS_DIR env var)")
        # Minimal admin endpoints so tests can query loaded plugins when
        # PluginLoader is created standalone (outside admin_app).
        try:
            @self.app.get('/api/v1/admin/plugins')
            def _admin_list_plugins():
                return {"plugins": self.list_plugins()}
        except Exception:
            # If app is not a FastAPI instance or route cannot be added,
            # ignore silently.
            pass
    
    async def load_all(self):
        """Загрузить все плагины: встроенные и внешние."""
        # 1. Загружаем встроенные плагины из core-service/plugins/
        await self._load_builtin_plugins()
        
        # 2. Загружаем внешние плагины если PLUGINS_DIR задана
        if self.external_plugins_dir:
            await self._load_external_plugins()
    
    async def _load_builtin_plugins(self):
        """Загрузить встроенные плагины из core-service/plugins/"""
        try:
            import plugins as plugins_package
        except ImportError:
            logger.debug("plugins package not found, skipping builtin plugin loading")
            return
        
        # Найти все подмодули в пакете plugins
        plugin_modules = list(pkgutil.iter_modules(
            plugins_package.__path__,
            prefix=plugins_package.__name__ + "."
        ))
        
        if not plugin_modules:
            logger.info("ℹ️ No builtin plugins found in plugins/ directory")
            return
        
        logger.info(f"🔍 Found {len(plugin_modules)} builtin plugin(s)")
        
        for _, module_name, _ in plugin_modules:
            await self.load_plugin(module_name, plugin_type="builtin")
    
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
            
            # Создаём экземпляр плагина
            plugin = plugin_class(self.app, self.db_session_maker, self.event_bus)
            
            # Перезаписываем metadata из plugin.json если они есть
            if metadata.get('name'):
                plugin.name = metadata['name']
            if metadata.get('version'):
                plugin.version = metadata['version']
            if metadata.get('description'):
                plugin.description = metadata.get('description', '')
            
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
            
            logger.info(f"✅ Loaded external plugin: {plugin.name} v{plugin.version}")
            
        except Exception as e:
            logger.error(f"❌ Failed to load module from {file_path}: {e}", exc_info=True)
    
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
