"""
Event Bus для коммуникации между плагинами.
Позволяет публиковать и подписываться на события с поддержкой wildcard-паттернов.
"""

from typing import Dict, List, Callable, Any
import asyncio
import logging

logger = logging.getLogger(__name__)


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
    
    def __init__(self):
        """Инициализация Event Bus."""
        self.subscribers: Dict[str, List[Callable]] = {}
    
    async def emit(self, event_name: str, data: Dict[str, Any]):
        """
        Опубликовать событие всем подписчикам.
        
        Args:
            event_name: Имя события (например: "device.state_changed")
            data: Данные события (словарь)
        """
        logger.debug(f"📢 Event: {event_name}, data: {data}")
        
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
        - "device.state_changed" - точное совпадение
        
        Args:
            event_name: Имя события
            pattern: Паттерн
            
        Returns:
            True если событие совпадает паттерну
        """
        if pattern == "*":
            return True
        if pattern.endswith(".*"):
            prefix = pattern[:-2]  # Убираем ".*"
            return event_name.startswith(f"{prefix}.")
        return event_name == pattern


# Глобальный singleton
event_bus = EventBus()
