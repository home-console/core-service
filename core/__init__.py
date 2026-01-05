"""
Core модули core-service.

Экспортирует основные компоненты для удобного импорта.
"""

# Re-export для обратной совместимости
from .event_bus import EventBus
from .dependencies import get_plugin_loader, get_event_bus, get_db_session, get_current_user
from .constants import *
from .health_monitor import HealthMonitor

__all__ = [
    'EventBus',
    'get_plugin_loader',
    'get_event_bus',
    'get_db_session',
    'get_current_user',
    'HealthMonitor',
]

