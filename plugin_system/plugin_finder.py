"""
Модуль для поиска плагинов (встроенных и внешних)
"""

import os
import pkgutil
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


class PluginFinder:
    """Поисковик плагинов"""
    
    EXCLUDED_MODULES = {'__init__', 'base', 'loader', 'embed', 'models', 'utils'}
    EXCLUDED_PATTERNS = ['_example', 'example', '_test', 'test', 'generate_', 'setup', 'migration']
    
    @staticmethod
    def find_builtin_plugins() -> List[Tuple[str, bool]]:
        """
        Найти все встроенные плагины в core-service/plugins/.
        
        Returns:
            Список кортежей (module_name, is_package)
        """
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
                return []
        
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
            return []
        
        if not plugin_modules:
            logger.info("ℹ️ No builtin plugins found in plugins/ directory")
            return []
        
        logger.info(f"🔍 Found {len(plugin_modules)} builtin plugin module(s)")
        
        # Фильтруем исключенные модули
        filtered_modules = []
        for module_name, is_package in plugin_modules:
            module_basename = module_name.split('.')[-1]
            
            # Пропускаем исключенные модули
            if module_basename in PluginFinder.EXCLUDED_MODULES:
                logger.debug(f"⏭️ Skipping excluded module: {module_name}")
                continue
            
            # Пропускаем модули, соответствующие исключенным паттернам
            if any(pattern in module_basename.lower() for pattern in PluginFinder.EXCLUDED_PATTERNS):
                logger.debug(f"⏭️ Skipping module matching excluded pattern: {module_name}")
                continue
            
            filtered_modules.append((module_name, is_package))
        
        return filtered_modules
    
    @staticmethod
    def find_external_plugins(external_plugins_dir: str) -> List[str]:
        """
        Найти все внешние плагины в PLUGINS_DIR.
        
        Args:
            external_plugins_dir: Путь к директории с внешними плагинами
            
        Returns:
            Список путей к плагинам
        """
        if not os.path.isdir(external_plugins_dir):
            logger.warning(f"❌ PLUGINS_DIR not found: {external_plugins_dir}")
            return []
        
        items = os.listdir(external_plugins_dir)
        
        if not items:
            logger.info(f"ℹ️ PLUGINS_DIR is empty: {external_plugins_dir}")
            return []
        
        logger.info(f"🔍 Scanning PLUGINS_DIR for plugins: {external_plugins_dir}")
        
        plugin_paths = []
        for item in sorted(items):
            item_path = os.path.join(external_plugins_dir, item)
            
            # Пропускаем скрытые файлы и __pycache__
            if item.startswith('.') or item == '__pycache__':
                continue
            
            plugin_paths.append(item_path)
        
        return plugin_paths
    
    @staticmethod
    def find_entry_file(package_path: str) -> Optional[str]:
        """
        Найти entry файл плагина (main.py или __init__.py).
        
        Args:
            package_path: Путь к директории плагина
            
        Returns:
            Путь к entry файлу или None
        """
        main_file = os.path.join(package_path, "main.py")
        init_file = os.path.join(package_path, "__init__.py")
        
        if os.path.exists(main_file):
            return main_file
        elif os.path.exists(init_file):
            return init_file
        else:
            logger.warning(f"⚠️ No main.py or __init__.py found in {package_path}")
            return None

