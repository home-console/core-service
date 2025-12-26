# PiKVM Client Service Plugin

## Обзор

Плагин для управления устройствами PiKVM через HTTP API и WebSocket. Плагин интегрирован в систему Home Console и предоставляет REST API endpoints для управления PiKVM устройствами.

## Возможности

- ✅ Управление питанием (включение/выключение/сброс)
- ✅ Управление кнопками питания
- ✅ Управление GPIO (переключение и импульсы)
- ✅ Управление Mass Storage Device (MSD)
- ✅ Мониторинг через WebSocket
- ✅ Сохранение событий WebSocket в MongoDB (опционально)

## Установка

### 1. Установка зависимостей

Плагин автоматически загружается системой Home Console. Убедитесь, что все зависимости установлены:

```bash
cd core-service
pip install -r requirements.txt
```

Зависимости плагина (уже включены в requirements.txt):
- `requests`
- `pydantic`
- `python-dotenv`
- `websocket-client`
- `pymongo` (опционально, для MongoDB)
- `urllib3`
- `pyotp`

## Конфигурация

### Переменные окружения

```bash
# Обязательные
PIKVM_HOST=192.168.1.100          # IP адрес или hostname PiKVM устройства
PIKVM_USERNAME=admin               # Имя пользователя
PIKVM_PASSWORD=your_password       # Пароль

# Опциональные
PIKVM_SECRET=                      # TOTP секрет для двухфакторной аутентификации
MONGODB_URI=mongodb://localhost:27017/  # URI для MongoDB (опционально)
MONGODB_DATABASE=pikvm_data       # Имя базы данных MongoDB
MONGODB_COLLECTION=websocket_events # Коллекция для событий WebSocket
DEBUG=false                        # Включить отладочное логирование
```

### Конфигурация через UI

Плагин можно настроить через веб-интерфейс Home Console:
1. Перейдите в раздел "Плагины"
2. Найдите "PiKVM Client Service"
3. Нажмите "Настроить"
4. Заполните параметры конфигурации

## API Endpoints

Все endpoints доступны по префиксу `/api/plugins/pikvm_client/`

### Системная информация

```http
GET /api/plugins/pikvm_client/info?fields=version,hostname
```

### Управление питанием

```http
# Получить состояние питания
GET /api/plugins/pikvm_client/power

# Управление питанием
POST /api/plugins/pikvm_client/power
Content-Type: application/json

{
  "action": "on",  # on, off, off_hard, reset_hard
  "wait": false
}

# Нажать кнопку питания
POST /api/plugins/pikvm_client/power/click
Content-Type: application/json

{
  "button": "power",  # power, power_long, reset
  "wait": false
}
```

### Управление GPIO

```http
# Получить состояние GPIO
GET /api/plugins/pikvm_client/gpio

# Переключить GPIO канал
POST /api/plugins/pikvm_client/gpio/switch
Content-Type: application/json

{
  "channel": 1,
  "state": 1,  # 0 или 1
  "wait": false
}

# Импульс GPIO канала
POST /api/plugins/pikvm_client/gpio/pulse
Content-Type: application/json

{
  "channel": 1,
  "delay": 1.0,  # Длительность импульса в секундах
  "wait": false
}
```

### Mass Storage Device

```http
# Получить состояние MSD
GET /api/plugins/pikvm_client/msd
```

### Логи системы

```http
GET /api/plugins/pikvm_client/logs?follow=false&seek=3600
```

### Проверка здоровья

```http
GET /api/plugins/pikvm_client/health
```

Ответ:
```json
{
  "status": "healthy",
  "http_connection": true,
  "websocket_active": true,
  "grpc_active": true,
  "mongodb_connected": true
}
```

## Использование через Actions

Плагин поддерживает действия (actions) для интеграции с другими компонентами системы:

### Включить питание

```json
{
  "action": "pikvm.power.on",
  "payload": {
    "device_id": "pikvm-1",
    "wait": false
  }
}
```

### Выключить питание

```json
{
  "action": "pikvm.power.off",
  "payload": {
    "device_id": "pikvm-1",
    "wait": false
  }
}
```

### Переключить GPIO

```json
{
  "action": "pikvm.gpio.switch",
  "payload": {
    "device_id": "pikvm-1",
    "channel": 1,
    "state": 1,
    "wait": false
  }
}
```

## WebSocket мониторинг

Плагин автоматически подключается к WebSocket API PiKVM и сохраняет события в MongoDB (если настроено). События включают:

- Состояние системы
- Изменения питания
- GPIO события
- Ошибки соединения

## Структура плагина

```
PIKVMClientService/
├── __init__.py              # Экспорт класса плагина
├── main.py                  # Основной класс плагина
├── manifest.json            # Метаданные плагина
├── README.md                # Документация
└── src/
    ├── controllers/
    │   ├── pikvm.py        # HTTP API контроллер
    │   └── WebSocket.py     # WebSocket клиент
    └── settings.py         # Настройки
```

## Устранение неполадок

### Плагин не загружается

1. Проверьте логи core-service
2. Убедитесь, что все зависимости установлены
3. Проверьте правильность переменных окружения

### Ошибки подключения к PiKVM

1. Проверьте доступность PiKVM устройства: `ping <PIKVM_HOST>`
2. Проверьте правильность учетных данных
3. Убедитесь, что PiKVM API доступен по HTTPS

### WebSocket не подключается

1. Проверьте настройки SSL (PiKVM часто использует самоподписанные сертификаты)
2. Проверьте логи плагина
3. Убедитесь, что WebSocket включен в конфигурации

## Безопасность

⚠️ **Важно:**

- Используйте сильные пароли для PiKVM
- Ограничьте доступ к API endpoints через firewall
- Для production рекомендуется использовать HTTPS для PiKVM API

## Лицензия

MIT
