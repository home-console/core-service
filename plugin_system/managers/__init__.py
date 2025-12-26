"""
Менеджеры плагин-системы

Модули управления различными аспектами плагинов:
- config: управление конфигурацией
- dependency: управление зависимостями
- lifecycle: управление жизненным циклом
- mode: управление режимами работы
- security: управление безопасностью
"""

from .config import PluginConfigManager, init_plugin_config_manager, get_plugin_config_manager
from .dependency import (
    PluginDependencyManager,
    init_plugin_dependency_manager,
    PluginDependency,
    DependencyType,
)
from .lifecycle import PluginLifecycleManager, init_plugin_lifecycle_manager
from .mode import PluginModeManager, init_plugin_mode_manager, PluginMode
from .security import PluginSecurityManager, init_plugin_security_manager

__all__ = [
    'PluginConfigManager',
    'init_plugin_config_manager',
    'get_plugin_config_manager',
    'PluginDependencyManager',
    'init_plugin_dependency_manager',
    'PluginDependency',
    'DependencyType',
    'PluginLifecycleManager',
    'init_plugin_lifecycle_manager',
    'PluginModeManager',
    'init_plugin_mode_manager',
    'PluginMode',
    'PluginSecurityManager',
    'init_plugin_security_manager',
]

