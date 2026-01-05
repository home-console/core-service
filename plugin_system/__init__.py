"""
Plugin System - модульная система управления плагинами.

Структура:
- base/ - базовые классы (base.py)
- managers/ - менеджеры (config, dependency, lifecycle, mode, security)
- loader.py - основная логика загрузки плагинов
- registry.py - реестр внешних плагинов
- metadata_reader.py - чтение метаданных из plugin.json
- archive_handler.py - работа с архивами (zip, tar.gz)
- installer.py - установка зависимостей
- router_manager.py - монтирование роутеров
- db_manager.py - работа с БД
- plugin_finder.py - поиск плагинов
"""

from .loader import PluginLoader
from .base import InternalPluginBase
from .registry import external_plugin_registry, ExternalPlugin, ExternalPluginRegistry
from .managers import (
    PluginConfigManager,
    PluginDependencyManager,
    PluginLifecycleManager,
    PluginModeManager,
    PluginSecurityManager,
    PluginMode,
    PluginDependency,
    DependencyType,
    init_plugin_config_manager,
    init_plugin_dependency_manager,
    init_plugin_lifecycle_manager,
    init_plugin_mode_manager,
    init_plugin_security_manager,
)

__all__ = [
    'PluginLoader',
    'InternalPluginBase',
    'external_plugin_registry',
    'ExternalPlugin',
    'ExternalPluginRegistry',
    'PluginConfigManager',
    'PluginDependencyManager',
    'PluginLifecycleManager',
    'PluginModeManager',
    'PluginSecurityManager',
    'PluginMode',
    'PluginDependency',
    'DependencyType',
    'init_plugin_config_manager',
    'init_plugin_dependency_manager',
    'init_plugin_lifecycle_manager',
    'init_plugin_mode_manager',
    'init_plugin_security_manager',
]

