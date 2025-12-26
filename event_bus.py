"""
Event Bus для коммуникации между плагинами.
Позволяет публиковать и подписываться на события с поддержкой wildcard-паттернов.
"""

from typing import Dict, List, Callable, Any, Optional
from datetime import datetime
from collections import deque
import asyncio
import logging

logger = logging.getLogger(__name__)


class EventLogEntry:
    """Запись в логе событий."""
    def __init__(self, event_name: str, data: Dict[str, Any], timestamp: Optional[datetime] = None):
        self.event_name = event_name
        self.data = data
        self.timestamp = timestamp or datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь для JSON."""
        return {
            "event_name": self.event_name,
            "data": self.data,
            "timestamp": self.timestamp.isoformat()
        }


class EventBus:
    """
    Простой in-process Event Bus для коммуникации между плагинами.
    
    Поддерживает подписку на события с использованием wildcard-паттернов:
    - "device.*" - все события, начинающиеся с "device."
    - "*" - все события
    - "device.state_changed" - точное совпадение
    
    Пример использования:
    
    ```python
    # Подписка
    async def on_device_changed(event_name, data):
        print(f"Device changed: {data}")
    
    await event_bus.subscribe("device.*", on_device_changed)
    
    # Публикация
    await event_bus.emit("device.state_changed", {
        "device_id": 1,
        "state": "on",
        "brightness": 100
    })
    ```
    """
    
    def __init__(self, max_log_size: int = 1000):
        """
        Инициализация Event Bus.
        
        Args:
            max_log_size: Максимальное количество записей в логе событий
        """
        self.subscribers: Dict[str, List[Callable]] = {}
        self.event_log: deque = deque(maxlen=max_log_size)
        self.stats: Dict[str, int] = {
            "total_events": 0,
            "events_by_type": {}
        }
    
    async def emit(self, event_name: str, data: Dict[str, Any]):
        """
        Опубликовать событие всем подписчикам.
        
        Args:
            event_name: Имя события (например: "device.state_changed")
            data: Данные события (словарь)
        """
        logger.info(f"📢 EVENT EMIT: {event_name}")
        logger.debug(f"📢 EVENT DATA: {data}")
        logger.debug(f"📢 SUBSCRIBERS: {list(self.subscribers.keys())}")
        
        # Сохранить в лог
        log_entry = EventLogEntry(event_name, data)
        self.event_log.append(log_entry)
        
        # Обновить статистику
        self.stats["total_events"] += 1
        self.stats["events_by_type"][event_name] = self.stats["events_by_type"].get(event_name, 0) + 1
        
        # Найти всех подписчиков с совпадающими паттернами
        for pattern, handlers in self.subscribers.items():
            if self._match_pattern(event_name, pattern):
                for handler in handlers:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler(event_name, data)
                        else:
                            handler(event_name, data)
                    except Exception as e:
                        logger.error(
                            f"❌ Error in event handler for '{event_name}' (pattern '{pattern}'): {e}",
                            exc_info=True
                        )
    
    def get_logs(self, limit: int = 100, event_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Получить последние записи из лога событий.
        
        Args:
            limit: Максимальное количество записей
            event_filter: Фильтр по имени события (поддерживает wildcards)
            
        Returns:
            Список записей лога
        """
        logs = list(self.event_log)
        
        # Применить фильтр если указан
        if event_filter:
            logs = [
                entry for entry in logs
                if self._match_pattern(entry.event_name, event_filter)
            ]
        
        # Вернуть последние N записей
        return [entry.to_dict() for entry in logs[-limit:]]
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получить статистику по событиям.
        
        Returns:
            Словарь со статистикой
        """
        return {
            "total_events": self.stats["total_events"],
            "events_by_type": self.stats["events_by_type"].copy(),
            "log_size": len(self.event_log),
            "subscribers_count": sum(len(handlers) for handlers in self.subscribers.values()),
            "subscribers_patterns": list(self.subscribers.keys())
        }
    
    def clear_log(self):
        """Очистить лог событий."""
        self.event_log.clear()
        self.stats["total_events"] = 0
        self.stats["events_by_type"] = {}
    
    async def subscribe(self, event_pattern: str, handler: Callable):
        """
        Подписаться на события по паттерну.
        
        Args:
            event_pattern: Паттерн события с поддержкой wildcards
            handler: Async или sync функция для обработки события
        """
        if event_pattern not in self.subscribers:
            self.subscribers[event_pattern] = []
        self.subscribers[event_pattern].append(handler)
        logger.debug(f"✅ Subscribed to pattern '{event_pattern}'")
    
    def _match_pattern(self, event_name: str, pattern: str) -> bool:
        """
        Проверить соответствие имени события паттерну.
        
        Поддерживаемые паттерны:
        - "*" - любое событие
        - "device.*" - события, начинающиеся с "device."
        - "device.*.toggle" - события вида device.SOMETHING.toggle
        - "device.state_changed" - точное совпадение
        
        Args:
            event_name: Имя события
            pattern: Паттерн
            
        Returns:
            True если событие совпадает паттерну
        """
        if pattern == "*":
            return True
        
        # Если нет звездочек, то это точное совпадение
        if "*" not in pattern:
            return event_name == pattern
        
        # Преобразуем паттерн в regex
        import re
        # Экранируем специальные символы кроме *
        escaped = re.escape(pattern)
        # Заменяем экранированные * на .*
        regex_pattern = escaped.replace(r"\*", ".*")
        # Добавляем якоря начала и конца
        regex_pattern = f"^{regex_pattern}$"
        
        return bool(re.match(regex_pattern, event_name))


# Глобальный singleton
event_bus = EventBus()
