# Оптимизации Core Service

## 🎯 Приоритетные оптимизации

### 1. ⚡ Параллельная загрузка плагинов

**Проблема:** Плагины загружаются последовательно, что замедляет старт приложения.

**Решение:** Загружать плагины параллельно с ограничением concurrency.

```python
# В plugin_system/loader.py
async def _load_builtin_plugins(self):
    """Загрузить встроенные плагины параллельно."""
    plugin_modules = PluginFinder.find_builtin_plugins()
    
    # Создаем семафор для ограничения параллелизма
    semaphore = asyncio.Semaphore(5)  # Максимум 5 плагинов одновременно
    
    async def load_with_semaphore(module_name, is_package):
        async with semaphore:
            return await self._load_single_plugin(module_name, is_package)
    
    # Загружаем все плагины параллельно
    tasks = [
        load_with_semaphore(module_name, is_package)
        for module_name, is_package in plugin_modules
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # Обрабатываем результаты...
```

**Ожидаемый эффект:** Ускорение старта на 60-80% при большом количестве плагинов.

---

### 2. 💾 Расширенное кэширование

**Проблема:** Кэширование используется только для списка устройств, много повторяющихся запросов.

**Решение:** Добавить кэширование для:
- Списка плагинов (TTL: 60 сек)
- Конфигурации плагинов (TTL: 300 сек)
- Метаданных устройств (TTL: 30 сек)
- Intent mappings (TTL: 300 сек)

```python
# В routes/plugins.py
@router.get("/plugins")
@cached(ttl=60, key_prefix="plugins")
async def list_plugins(request: Request):
    # ... существующий код ...
    pass

# В routes/devices.py - уже есть, но можно улучшить
@router.get("/devices/{device_id}")
@cached(ttl=30, key_prefix="device")
async def get_device(device_id: str):
    # ... существующий код ...
    pass
```

**Ожидаемый эффект:** Снижение нагрузки на БД на 40-60%.

---

### 3. 🗄️ Оптимизация запросов к БД (Eager Loading)

**Проблема:** N+1 запросы при загрузке связанных данных.

**Решение:** Использовать `selectinload` для предзагрузки связей.

```python
# В routes/plugins.py - исправить N+1 проблему
from sqlalchemy.orm import selectinload

@router.get("/plugins")
async def list_plugins(request: Request):
    async with get_session() as db:
        # Загружаем плагины с версиями одним запросом
        result = await db.execute(
            select(Plugin)
            .options(selectinload(Plugin.versions))  # Eager loading
        )
        plugins = result.scalars().all()
        
        # Теперь versions уже загружены, не нужны отдельные запросы
        for p in plugins:
            # p.versions уже доступны без дополнительных запросов
            pass
```

**Ожидаемый эффект:** Снижение количества запросов к БД на 70-90%.

---

### 4. 📊 Database индексы

**Проблема:** Отсутствуют индексы на часто используемых полях.

**Решение:** Добавить индексы через миграцию:

```python
# В migrations/ или через Alembic
CREATE INDEX idx_device_is_online ON devices(is_online);
CREATE INDEX idx_device_type ON devices(type);
CREATE INDEX idx_plugin_binding_device_id ON plugin_bindings(device_id);
CREATE INDEX idx_plugin_binding_enabled ON plugin_bindings(enabled);
CREATE INDEX idx_intent_mapping_intent_name ON intent_mappings(intent_name);
CREATE INDEX idx_device_link_source ON device_links(source_device_id);
CREATE INDEX idx_device_link_target ON device_links(target_device_id);
```

**Ожидаемый эффект:** Ускорение запросов на 50-80%.

---

### 5. 🚀 Event Bus оптимизация

**Проблема:** Batch processing может быть улучшен для больших нагрузок.

**Решение:** 
- Увеличить batch size для частых событий
- Добавить приоритеты для критичных событий
- Использовать отдельные очереди для разных типов событий

```python
# В event_bus.py
class EventBus:
    def __init__(self, max_log_size: int = 1000, debounce_ms: int = 100, batch_size: int = 20):
        # Увеличиваем batch_size для лучшей производительности
        self.batch_size = batch_size
        
        # Разделяем очереди по приоритетам
        self.high_priority_queue = asyncio.Queue()
        self.normal_priority_queue = asyncio.Queue()
        
    async def emit(self, event_name: str, data: Dict[str, Any], priority: str = "normal"):
        """Публикация с приоритетом."""
        queue = self.high_priority_queue if priority == "high" else self.normal_priority_queue
        await queue.put((event_name, data))
```

**Ожидаемый эффект:** Улучшение пропускной способности на 30-50%.

---

### 6. 🗜️ Response Compression

**Проблема:** Большие JSON ответы передаются без сжатия.

**Решение:** Добавить GZip middleware.

```python
# В app.py
from fastapi.middleware.gzip import GZipMiddleware

app.add_middleware(
    GZipMiddleware,
    minimum_size=1000  # Сжимать ответы больше 1KB
)
```

**Ожидаемый эффект:** Снижение трафика на 60-80% для больших ответов.

---

### 7. 🔄 Connection Pool оптимизация

**Проблема:** Настройки пула могут быть не оптимальны для production.

**Решение:** Настроить пул в зависимости от нагрузки.

```python
# В db.py
import os

# Настройки из переменных окружения
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "20"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))
DB_POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "3600"))

pool_kwargs = {
    "pool_size": DB_POOL_SIZE,
    "max_overflow": DB_MAX_OVERFLOW,
    "pool_pre_ping": True,
    "pool_recycle": DB_POOL_RECYCLE,
    "pool_reset_on_return": "commit",  # Оптимизация для async
}
```

**Ожидаемый эффект:** Лучшая производительность при высокой нагрузке.

---

### 8. 📝 Query Result Caching

**Проблема:** Результаты сложных запросов не кэшируются.

**Решение:** Добавить кэширование результатов запросов с инвалидацией.

```python
# В utils/cache.py добавить
async def cache_query_result(query_key: str, query_func, ttl: int = 300):
    """Кэшировать результат запроса."""
    cached = await cache_get(query_key)
    if cached is not None:
        return cached
    
    result = await query_func()
    await cache_set(query_key, result, ttl=ttl)
    return result

# Использование:
async def get_devices_with_bindings():
    return await cache_query_result(
        "devices:with_bindings",
        lambda: execute_complex_query(),
        ttl=30
    )
```

---

### 9. ⚡ Async HTTP Client Pool

**Проблема:** HTTP клиент уже оптимизирован, но можно добавить retry logic.

**Решение:** Добавить автоматические повторы для неустойчивых соединений.

```python
# В utils/http_client.py
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
async def http_request_with_retry(method: str, url: str, **kwargs):
    """HTTP запрос с автоматическими повторами."""
    client = _get_http_client()
    return await client.request(method, url, **kwargs)
```

---

### 10. 🔍 Database Query Logging (только для dev)

**Проблема:** Сложно отслеживать медленные запросы.

**Решение:** Добавить логирование медленных запросов.

```python
# В db.py
import time

@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        start_time = time.time()
        try:
            yield session
            await session.commit()
            
            # Логируем медленные запросы (только в dev)
            if os.getenv("LOG_SLOW_QUERIES") == "true":
                duration = time.time() - start_time
                if duration > 0.1:  # Больше 100ms
                    logger.warning(f"Slow session: {duration:.3f}s")
        except Exception as e:
            await session.rollback()
            raise
```

---

## 📈 Метрики для мониторинга

Добавить метрики для отслеживания производительности:

1. **Database:**
   - Среднее время запроса
   - Количество запросов в секунду
   - Размер connection pool

2. **Cache:**
   - Hit rate (должен быть > 70%)
   - Miss rate
   - Среднее время доступа

3. **Event Bus:**
   - Событий в секунду
   - Размер очереди
   - Время обработки batch

4. **Plugins:**
   - Время загрузки плагинов
   - Количество активных плагинов
   - Ошибки загрузки

---

## 🎯 Приоритет внедрения

1. **Высокий приоритет:**
   - Database индексы (быстро, большой эффект)
   - Eager loading (средняя сложность, большой эффект)
   - Response compression (быстро, средний эффект)

2. **Средний приоритет:**
   - Расширенное кэширование (средняя сложность, средний эффект)
   - Параллельная загрузка плагинов (средняя сложность, средний эффект)
   - Connection pool оптимизация (быстро, средний эффект)

3. **Низкий приоритет:**
   - Event Bus оптимизация (сложно, малый эффект)
   - Query result caching (средняя сложность, малый эффект)
   - HTTP retry logic (быстро, малый эффект)

---

## 🧪 Тестирование оптимизаций

После внедрения каждой оптимизации:

1. Запустить нагрузочные тесты
2. Сравнить метрики до/после
3. Проверить на production-like данных
4. Мониторить в течение недели

---

## 📝 Примечания

- Все оптимизации должны быть опциональными через переменные окружения
- Не оптимизировать преждевременно - сначала измерить
- Фокус на реальных узких местах, а не на теоретических

