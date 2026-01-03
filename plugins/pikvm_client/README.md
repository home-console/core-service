# PiKVM Client Service Plugin

## Обзор

Плагин для управления устройствами PiKVM через HTTP API и WebSocket. Плагин интегрирован в систему Home Console и предоставляет REST API endpoints для управления PiKVM устройствами.

## Возможности

- ✅ Управление питанием (включение/выключение/сброс)
- ✅ Управление кнопками питания
- ✅ Управление GPIO (переключение и импульсы)
- ✅ Управление Mass Storage Device (MSD)
- ✅ Мониторинг через WebSocket
- ✅ Поддержка нескольких устройств одновременно

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
- `urllib3`
- `pyotp`

## Конфигурация

### Поддержка нескольких устройств

Плагин поддерживает работу с несколькими устройствами PiKVM одновременно. Каждое устройство должно иметь уникальный `device_id`.

### Конфигурация через UI (рекомендуется)

Плагин можно настроить через веб-интерфейс Home Console:
1. Перейдите в раздел "Плагины"
2. Найдите "PiKVM Client Service"
3. Нажмите "Настроить"
4. Заполните параметры конфигурации

#### Формат конфигурации (JSON)

```json
{
  "devices": [
    {
      "device_id": "pikvm-server1",
      "host": "192.168.1.100",
      "username": "admin",
      "password": "password1",
      "secret": null,
      "enabled": true
    },
    {
      "device_id": "pikvm-server2",
      "host": "192.168.1.101",
      "username": "admin",
      "password": "password2",
      "secret": null,
      "enabled": true
    }
  ],
  "enable_websocket": true,
  "debug": false
}
```

### Переменные окружения (обратная совместимость)

Для одного устройства можно использовать старый формат:

```bash
# Обязательные
PIKVM_HOST=192.168.1.100          # IP адрес или hostname PiKVM устройства
PIKVM_USERNAME=admin               # Имя пользователя
PIKVM_PASSWORD=your_password       # Пароль

# Опциональные
PIKVM_SECRET=                      # TOTP секрет для двухфакторной аутентификации
DEBUG=false                        # Включить отладочное логирование
```

## API Endpoints

Все endpoints доступны по префиксу `/api/plugins/pikvm_client/`

### Список устройств

```http
GET /api/plugins/pikvm_client/devices
```

Ответ:
```json
{
  "devices": [
    {
      "device_id": "pikvm-server1",
      "host": "192.168.1.100",
      "enabled": true
    },
    {
      "device_id": "pikvm-server2",
      "host": "192.168.1.101",
      "enabled": true
    }
  ],
  "count": 2
}
```

### Системная информация

```http
# Для конкретного устройства
GET /api/plugins/pikvm_client/info?device_id=pikvm-server1&fields=version,hostname

# Если устройство одно, device_id можно не указывать
GET /api/plugins/pikvm_client/info?fields=version,hostname
```

### Управление питанием

```http
# Получить состояние питания
GET /api/plugins/pikvm_client/power?device_id=pikvm-server1

# Управление питанием
POST /api/plugins/pikvm_client/power
Content-Type: application/json

{
  "device_id": "pikvm-server1",  # обязательно, если устройств несколько
  "action": "on",  # on, off, off_hard, reset_hard
  "wait": false
}

# Нажать кнопку питания
POST /api/plugins/pikvm_client/power/click
Content-Type: application/json

{
  "device_id": "pikvm-server1",  # обязательно, если устройств несколько
  "button": "power",  # power, power_long, reset
  "wait": false
}
```

### Управление GPIO

```http
# Получить состояние GPIO
GET /api/plugins/pikvm_client/gpio?device_id=pikvm-server1

# Переключить GPIO канал
POST /api/plugins/pikvm_client/gpio/switch
Content-Type: application/json

{
  "device_id": "pikvm-server1",  # обязательно, если устройств несколько
  "channel": 1,
  "state": 1,  # 0 или 1
  "wait": false
}

# Импульс GPIO канала
POST /api/plugins/pikvm_client/gpio/pulse
Content-Type: application/json

{
  "device_id": "pikvm-server1",  # обязательно, если устройств несколько
  "channel": 1,
  "delay": 1.0,  # Длительность импульса в секундах
  "wait": false
}
```

### Mass Storage Device

```http
# Получить состояние MSD
GET /api/plugins/pikvm_client/msd?device_id=pikvm-server1
```

### Логи системы

```http
GET /api/plugins/pikvm_client/logs?device_id=pikvm-server1&follow=false&seek=3600
```

### Проверка здоровья

```http
# Проверка всех устройств
GET /api/plugins/pikvm_client/health

# Проверка конкретного устройства
GET /api/plugins/pikvm_client/health?device_id=pikvm-server1
```

Ответ (для всех устройств):
```json
{
  "status": "healthy",
  "configured": true,
  "devices": {
    "pikvm-server1": {
      "status": "healthy",
      "http_connection": true,
      "websocket_active": true
    },
    "pikvm-server2": {
      "status": "healthy",
      "http_connection": true,
      "websocket_active": true
    }
  }
}
```

Ответ (для одного устройства):
```json
{
  "status": "healthy",
  "device_id": "pikvm-server1",
  "configured": true,
  "http_connection": true,
  "websocket_active": true
}
```

## Использование через Actions

Плагин поддерживает действия (actions) для интеграции с другими компонентами системы. **Важно:** `device_id` теперь обязателен, если настроено несколько устройств.

### Включить питание

```json
{
  "action": "pikvm.power.on",
  "payload": {
    "device_id": "pikvm-server1",  # обязательно
    "wait": false
  }
}
```

### Выключить питание

```json
{
  "action": "pikvm.power.off",
  "payload": {
    "device_id": "pikvm-server1",  # обязательно
    "wait": false
  }
}
```

### Переключить GPIO

```json
{
  "action": "pikvm.gpio.switch",
  "payload": {
    "device_id": "pikvm-server1",  # обязательно
    "channel": 1,
    "state": 1,
    "wait": false
  }
}
```

## WebSocket мониторинг

Плагин автоматически подключается к WebSocket API каждого настроенного устройства PiKVM. Все события:

1. **Логируются** через стандартный Python logging с префиксом `[device_id]` (автономная работа)
2. **Публикуются** в Event Bus Home Console (если доступен) для интеграции с другими плагинами

### События WebSocket

- `websocket.connected` - соединение установлено
- `websocket.closed` - соединение закрыто
- `websocket.error` - ошибка соединения
- `websocket.message` - получено сообщение
- `websocket.status` - обновление статуса

### События действий

- `power.controlled` - управление питанием
- `power.button_clicked` - нажатие кнопки питания
- `gpio.switched` - переключение GPIO
- `gpio.pulsed` - импульс GPIO

Все события содержат `device_id` для идентификации устройства.

### Интеграция с другими плагинами

Другие плагины могут подписаться на события PiKVM:

```python
async def on_pikvm_event(event_name: str, data: dict):
    print(f"PiKVM event: {event_name}, device: {data['device_id']}")

# Подписка на все события PiKVM
await event_bus.subscribe("pikvm_client.*", on_pikvm_event)

# Подписка на конкретные события
await event_bus.subscribe("pikvm_client.power.*", on_pikvm_event)
await event_bus.subscribe("pikvm_client.websocket.*", on_pikvm_event)
```

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
