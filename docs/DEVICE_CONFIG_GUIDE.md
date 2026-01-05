# Глобальная конфигурация устройств

## Обзор

Ядро системы теперь поддерживает глобальные настройки для управления устройствами, которые могут быть переопределены для каждого плагина:

- **device_online_timeout** - время в секундах, после которого устройство считается оффлайн (по умолчанию 300 секунд = 5 минут)
- **device_poll_interval** - интервал опроса устройств в секундах (по умолчанию 60 секунд = 1 минута)

## Настройка через PluginConfigManager

### Через API

```bash
# Установить глобальные настройки для плагина
POST /api/v1/admin/plugins/{plugin_id}/config
{
  "device_online_timeout": 600,  # 10 минут
  "device_poll_interval": 120    # 2 минуты
}
```

### Через файл конфигурации

Создайте файл `config/yandex_smart_home.yaml`:

```yaml
plugin_id: yandex_smart_home
mode: in_process
enabled: true
config:
  sync_interval: 300
  full_sync_on_periodic: false
device_online_timeout: 600  # 10 минут
device_poll_interval: 120   # 2 минуты
```

### Через переменные окружения

```bash
# Для конкретного плагина
PLUGIN_YANDEX_SMART_HOME_DEVICE_ONLINE_TIMEOUT=600
PLUGIN_YANDEX_SMART_HOME_DEVICE_POLL_INTERVAL=120
```

## Значения по умолчанию

- **device_online_timeout**: 300 секунд (5 минут)
- **device_poll_interval**: 
  - Общий: 60 секунд (1 минута)
  - Для yandex_smart_home: 300 секунд (5 минут)

## Использование в плагинах

Плагины автоматически получают эти параметры через `self.config`:

```python
# В плагине
online_timeout = self.config.get('device_online_timeout', 300)
poll_interval = self.config.get('device_poll_interval', 60)
```

## Приоритет настроек

1. **Высший приоритет**: Значения из `config` плагина (через API или файл)
2. **Средний приоритет**: Глобальные настройки из PluginConfigManager
3. **Низший приоритет**: Значения по умолчанию

## Примеры использования

### Для быстрой синхронизации (частое обновление)

```yaml
device_online_timeout: 180  # 3 минуты
device_poll_interval: 30    # 30 секунд
```

### Для экономии ресурсов (редкое обновление)

```yaml
device_online_timeout: 900   # 15 минут
device_poll_interval: 600    # 10 минут
```

### Для разных типов устройств

Можно настроить разные значения для разных плагинов:

```yaml
# config/yandex_smart_home.yaml
device_online_timeout: 300
device_poll_interval: 300

# config/home_assistant.yaml
device_online_timeout: 120
device_poll_interval: 60
```

## API Endpoints

### Получить конфигурацию плагина

```bash
GET /api/v1/admin/plugins/{plugin_id}/config
```

Ответ включает:
```json
{
  "plugin_id": "yandex_smart_home",
  "device_online_timeout": 300,
  "device_poll_interval": 300,
  "config": {
    "sync_interval": 300,
    ...
  }
}
```

### Установить конфигурацию

```bash
POST /api/v1/admin/plugins/{plugin_id}/config
{
  "device_online_timeout": 600,
  "device_poll_interval": 120
}
```

