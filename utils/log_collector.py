"""
Application Log Collector - собирает все логи приложения в память для просмотра через API.
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from collections import deque
import threading


class LogEntry:
    """Запись лога приложения."""
    def __init__(
        self,
        level: str,
        logger_name: str,
        message: str,
        timestamp: Optional[datetime] = None,
        module: Optional[str] = None,
        exc_info: Optional[str] = None
    ):
        self.level = level
        self.logger_name = logger_name
        self.message = message
        self.timestamp = timestamp or datetime.utcnow()
        self.module = module or logger_name.split('.')[0] if logger_name else 'unknown'
        self.exc_info = exc_info
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь для JSON."""
        return {
            "level": self.level,
            "logger_name": self.logger_name,
            "module": self.module,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "exc_info": self.exc_info
        }


class ApplicationLogHandler(logging.Handler):
    """Кастомный handler для сбора логов приложения."""
    
    def __init__(self, max_size: int = 5000):
        super().__init__()
        self.max_size = max_size
        self.logs: deque = deque(maxlen=max_size)
        self.lock = threading.Lock()
    
    def emit(self, record: logging.LogRecord):
        """Обработать запись лога."""
        try:
            # Извлечь информацию об исключении если есть
            exc_info = None
            if record.exc_info:
                import traceback
                exc_info = ''.join(traceback.format_exception(*record.exc_info))
            
            # Определить модуль из logger name
            module = record.name.split('.')[0] if record.name else 'unknown'
            
            # Используем record.getMessage() вместо format() чтобы избежать проблем
            try:
                message = record.getMessage()
            except Exception:
                message = str(record.msg)
            
            log_entry = LogEntry(
                level=record.levelname,
                logger_name=record.name,
                message=message,
                timestamp=datetime.fromtimestamp(record.created),
                module=module,
                exc_info=exc_info
            )
            
            # Используем неблокирующий подход
            if self.lock.acquire(blocking=False):
                try:
                    self.logs.append(log_entry)
                finally:
                    self.lock.release()
        except Exception:
            # Не логируем ошибки в лог-хэндлере, чтобы избежать рекурсии
            # Просто игнорируем ошибки
            pass
    
    def get_logs(
        self,
        limit: int = 100,
        level: Optional[str] = None,
        module: Optional[str] = None,
        search: Optional[str] = None,
        logger_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Получить логи с фильтрацией.
        
        Args:
            limit: Максимальное количество записей
            level: Фильтр по уровню (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            module: Фильтр по модулю (например, 'core_service', 'plugin')
            search: Поиск по сообщению
            logger_name: Фильтр по имени логгера
        """
        with self.lock:
            logs = list(self.logs)
        
        # Применить фильтры
        filtered = logs
        
        if level:
            filtered = [log for log in filtered if log.level == level.upper()]
        
        if module:
            module_lower = module.lower()
            filtered = [log for log in filtered if log.module.lower().startswith(module_lower)]
        
        if logger_name:
            logger_lower = logger_name.lower()
            filtered = [log for log in filtered if logger_lower in log.logger_name.lower()]
        
        if search:
            search_lower = search.lower()
            filtered = [
                log for log in filtered
                if search_lower in log.message.lower() or
                   search_lower in log.logger_name.lower()
            ]
        
        # Вернуть последние N записей
        return [log.to_dict() for log in filtered[-limit:]]
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику по логам."""
        with self.lock:
            logs = list(self.logs)
        
        stats = {
            "total_logs": len(logs),
            "by_level": {},
            "by_module": {},
            "by_logger": {}
        }
        
        for log in logs:
            # По уровням
            stats["by_level"][log.level] = stats["by_level"].get(log.level, 0) + 1
            
            # По модулям
            stats["by_module"][log.module] = stats["by_module"].get(log.module, 0) + 1
            
            # По логгерам (топ 10)
            logger_short = log.logger_name.split('.')[-1] if '.' in log.logger_name else log.logger_name
            stats["by_logger"][logger_short] = stats["by_logger"].get(logger_short, 0) + 1
        
        return stats
    
    def clear(self):
        """Очистить логи."""
        with self.lock:
            self.logs.clear()


# Глобальный экземпляр коллектора логов
application_log_collector = ApplicationLogHandler(max_size=5000)

