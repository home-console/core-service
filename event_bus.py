"""
Event Bus для коммуникации между плагинами.
Позволяет публиковать и подписываться на события с поддержкой wildcard-паттернов.
"""

from typing import Dict, List, Callable, Any, Optional
from datetime import datetime, timedelta
from collections import deque, defaultdict
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
    Оптимизированный in-process Event Bus для коммуникации между плагинами.
    
    Поддерживает:
    - Подписку на события с использованием wildcard-паттернов
    - Debouncing для частых событий
    - Batch обработку событий
    - Асинхронную очередь для обработки
    
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
    
    def __init__(self, max_log_size: int = 1000, debounce_ms: int = 100, batch_size: int = 10):
        """
        Инициализация Event Bus.
        
        Args:
            max_log_size: Максимальное количество записей в логе событий
            debounce_ms: Время debounce в миллисекундах (для одинаковых событий)
            batch_size: Размер батча для batch обработки
        """
        self.subscribers: Dict[str, List[Callable]] = {}
        self.event_log: deque = deque(maxlen=max_log_size)
        self.stats: Dict[str, int] = {
            "total_events": 0,
            "events_by_type": {},
            "debounced_events": 0,
            "batched_events": 0
        }
        
        # Оптимизация: debouncing для частых событий
        self.debounce_ms = debounce_ms
        self.debounce_timers: Dict[str, asyncio.Task] = {}
        self.pending_events: Dict[str, Dict[str, Any]] = {}
        
        # Оптимизация: batch обработка
        self.batch_size = batch_size
        self.event_queue: asyncio.Queue = asyncio.Queue()
        self.batch_processor_task: Optional[asyncio.Task] = None
        
        # Запускаем batch processor
        self._start_batch_processor()
    
    def _start_batch_processor(self):
        """Запустить фоновую задачу для batch обработки событий."""
        async def process_batch():
            batch = []
            while True:
                try:
                    # Собираем события в батч
                    event = await asyncio.wait_for(self.event_queue.get(), timeout=0.1)
                    batch.append(event)
                    
                    # Если батч заполнен или прошло время, обрабатываем
                    if len(batch) >= self.batch_size:
                        await self._process_batch(batch)
                        batch = []
                except asyncio.TimeoutError:
                    # Таймаут - обрабатываем накопленный батч
                    if batch:
                        await self._process_batch(batch)
                        batch = []
                except Exception as e:
                    logger.error(f"Error in batch processor: {e}", exc_info=True)
        
        self.batch_processor_task = asyncio.create_task(process_batch())
    
    async def _process_batch(self, batch: List[tuple]):
        """Обработать батч событий."""
        # Обрабатываем события параллельно
        tasks = []
        for event_name, data in batch:
            # Найти всех подписчиков с совпадающими паттернами
            for pattern, handlers in self.subscribers.items():
                if self._match_pattern(event_name, pattern):
                    for handler in handlers:
                        tasks.append(self._safe_call_handler(handler, event_name, data))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            self.stats["batched_events"] += len(batch)
    
    async def _safe_call_handler(self, handler: Callable, event_name: str, data: Dict[str, Any]):
        """Безопасный вызов обработчика события."""
        try:
            if asyncio.iscoroutinefunction(handler):
                await handler(event_name, data)
            else:
                handler(event_name, data)
        except Exception as e:
            logger.error(
                f"❌ Error in event handler for '{event_name}': {e}",
                exc_info=True
            )
    
    async def _debounced_emit(self, event_name: str, data: Dict[str, Any]):
        """Внутренний метод для обработки события после debounce."""
        # Сохранить в лог
        log_entry = EventLogEntry(event_name, data)
        self.event_log.append(log_entry)
        
        # Обновить статистику
        self.stats["total_events"] += 1
        self.stats["events_by_type"][event_name] = self.stats["events_by_type"].get(event_name, 0) + 1
        
        # Добавляем в очередь для batch обработки
        await self.event_queue.put((event_name, data))
    
    async def emit(self, event_name: str, data: Dict[str, Any], debounce: bool = True):
        """
        Опубликовать событие всем подписчикам.
        
        Args:
            event_name: Имя события (например: "device.state_changed")
            data: Данные события (словарь)
            debounce: Использовать ли debouncing (по умолчанию True)
        """
        logger.debug(f"📢 EVENT EMIT: {event_name}")
        
        if not debounce:
            # Немедленная обработка без debounce
            await self._debounced_emit(event_name, data)
            return
        
        # Debouncing: отменяем предыдущий таймер для этого события
        if event_name in self.debounce_timers:
            self.debounce_timers[event_name].cancel()
        
        # Сохраняем последние данные события
        self.pending_events[event_name] = data
        
        # Создаем новый таймер
        async def delayed_emit():
            await asyncio.sleep(self.debounce_ms / 1000.0)
            if event_name in self.pending_events:
                await self._debounced_emit(event_name, self.pending_events[event_name])
                del self.pending_events[event_name]
                if event_name in self.debounce_timers:
                    del self.debounce_timers[event_name]
                self.stats["debounced_events"] += 1
        
        self.debounce_timers[event_name] = asyncio.create_task(delayed_emit())
    
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


# Глобальный singleton удален - создавать через lifespan в app.py
# Для обратной совместимости со старым кодом (deprecated)
_event_bus_instance: Optional[EventBus] = None

def get_event_bus() -> EventBus:
    """
    Получить глобальный экземпляр event_bus (deprecated).
    
    ВНИМАНИЕ: Используйте только для обратной совместимости.
    В новом коде передавайте event_bus через DI или app.state.
    """
    global _event_bus_instance
    if _event_bus_instance is None:
        logger.warning("Creating global event_bus instance (deprecated - use DI instead)")
        _event_bus_instance = EventBus()
    return _event_bus_instance

# Для обратной совместимости (deprecated)
# Используйте app.state.event_bus или Depends вместо этого
event_bus = get_event_bus()
