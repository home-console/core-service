# Миграция PIKVMClientService в плагин

## Что было сделано

Проект `pikvmclientservice` был успешно преобразован в плагин для системы Home Console.

### Изменения

1. **Создан `manifest.json`** - метаданные плагина с описанием действий, endpoints и конфигурации
2. **Преобразован `main.py`** - теперь это класс `PikvmClientPlugin`, наследующийся от `InternalPluginBase`
3. **Добавлены FastAPI роуты** - REST API endpoints для управления PiKVM через HTTP
4. **Интегрированы существующие компоненты**:
   - WebSocket клиент подключается автоматически
   - MongoDB handler для сохранения событий

### Структура плагина

```
PIKVMClientService/
├── __init__.py              # Экспорт PikvmClientPlugin
├── main.py                  # Класс плагина с роутами
├── manifest.json            # Метаданные плагина
├── README.md                # Документация
└── src/                     # Исходный код (без изменений)
    ├── controllers/
    ├── generated/
    ├── grpc_server.py
    └── settings.py
```

### Как использовать

1. **Настройка через переменные окружения:**
   ```bash
   export PIKVM_HOST=192.168.1.100
   export PIKVM_USERNAME=admin
   export PIKVM_PASSWORD=your_password
   ```

2. **Или через конфигурацию плагина в UI:**
   - Перейдите в раздел "Плагины"
   - Найдите "PiKVM Client Service"
   - Нажмите "Настроить"

3. **API endpoints доступны по адресу:**
   ```
   /api/plugins/pikvm_client/*
   ```

### Примеры использования

#### Включить питание через API:
```bash
curl -X POST http://localhost:11000/api/plugins/pikvm_client/power \
  -H "Content-Type: application/json" \
  -d '{"action": "on", "wait": false}'
```

#### Получить состояние питания:
```bash
curl http://localhost:11000/api/plugins/pikvm_client/power
```

#### Проверка здоровья:
```bash
curl http://localhost:11000/api/plugins/pikvm_client/health
```

### Что осталось без изменений

- Весь исходный код в `src/` остался без изменений (кроме удаления старого main.py)
- WebSocket клиент работает как раньше
- Все контроллеры и утилиты сохранены

### Что было удалено

- gRPC сервер - не нужен, так как есть REST API через FastAPI
- Старый `src/main.py` - не нужен, так как плагин имеет свой main.py

### Преимущества плагина

✅ Автоматическая загрузка при старте системы  
✅ Интеграция с системой событий Home Console  
✅ REST API endpoints для управления  
✅ Поддержка действий (actions) для интеграции  
✅ Конфигурация через UI  
✅ Логирование через систему Home Console  
✅ Управление жизненным циклом через SDK  

### Следующие шаги

1. Убедитесь, что все зависимости установлены
2. Настройте переменные окружения или конфигурацию плагина
3. Перезапустите core-service
4. Проверьте, что плагин загрузился: `/api/plugins/pikvm_client/health`

