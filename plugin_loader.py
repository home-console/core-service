"""
Обратная совместимость: импорт из новой модульной структуры.

Вся логика перенесена в core-service/plugin_system/
"""

from .plugin_system import PluginLoader

__all__ = ['PluginLoader']
