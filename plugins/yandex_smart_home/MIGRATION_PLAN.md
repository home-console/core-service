# План миграции Yandex Smart Home Plugin

## 🎯 Цель
Привести код к чистой модульной архитектуре: убрать дубли, перенести всю логику в соответствующие модули, оставить в `main.py` только glue code.

---

## 📊 Текущее состояние

### Файлы:
- ✅ `api/client.py` - YandexAPIClient (готов)
- ✅ `api/utils.py` - утилиты (готов)
- ✅ `auth/manager.py` - YandexAuthManager (готов)
- ✅ `auth/models.py` - YandexAccount (готов)
- ✅ `devices/manager.py` - DeviceManager (готов)
- ✅ `state/state_manager.py` - DeviceStateManager (готов)
- ✅ `handlers/routes.py` - RouteHandlers (частично готов)
- ⚠️ `main.py` - содержит много логики, которую нужно перенести
- ⚠️ `handler.py` - старая версия (используется через __init__.py)
- ❓ `api.py`, `auth.py` - нужно проверить, используются ли

### Проблемы в `main.py`:
1. **Прямые HTTP вызовы** (12 вхождений `http.client`) вместо `YandexAPIClient`
2. **Методы не в RouteHandlers**: `sync_devices`, `sync_device_states`, `auto_discover_new_devices`, `handle_alice_request`, `list_intents`, `create_intent`, `update_intent`, `delete_intent`
3. **Дублирование логики**: `_update_device_status` дублирует `DeviceStateManager.update_device_status`
4. **Методы команд**: `_send_yandex_command`, `_get_device_state` должны использовать менеджеры

---

## 📋 План выполнения (по шагам)

### ШАГ 1: Переключить entrypoint на main.py
**Файл**: `__init__.py`
```python
# Было:
from .handler import YandexSmartHomePlugin

# Станет:
from .main import YandexSmartHomePlugin
```
**Проверка**: После этого система должна использовать `main.py`

---

### ШАГ 2: Заменить прямые HTTP вызовы на YandexAPIClient

#### 2.1 Метод `list_devices_proxy` (строка 273)
**Было**: Прямой `http.client` вызов
**Станет**: Использовать `self.api_client.get_devices(access_token)`
**Примечание**: Уже есть в `RouteHandlers.list_devices_proxy` (строка 140), но в `main.py` есть своя версия

#### 2.2 Метод `_get_device_full_data` (строка 481)
**Было**: Прямой `http.client` вызов
**Станет**: Использовать `self.api_client.get_device(access_token, yandex_device_id)`

#### 2.3 Метод `_get_device_state` (строка 626)
**Было**: Прямой `http.client` вызов
**Станет**: Использовать `self.state_manager.get_device_state(access_token, device_id, self.api_client)`

#### 2.4 Метод `_send_yandex_command` (строка 694)
**Было**: Прямой `http.client` вызов
**Станет**: Использовать `self.device_manager.send_command(access_token, device_id, action, params)`

**Результат**: В `main.py` не должно быть `http.client` (кроме импорта, который можно удалить)

---

### ШАГ 3: Удалить дублирующиеся методы

#### 3.1 Метод `_update_device_status` (строка 388)
**Действие**: Удалить, использовать `self.state_manager.update_device_status()`

#### 3.2 Методы `_convert_action_to_yandex_params` и `_map_action_to_yandex_type` (строки 795, 827)
**Действие**: Удалить, использовать `self.device_manager.send_command()` (там уже есть эта логика)

---

### ШАГ 4: Перенести HTTP handlers в RouteHandlers

#### 4.1 `sync_devices` (строка 851)
- Перенести в `RouteHandlers.sync_devices()`
- Использовать `self.plugin.device_manager.sync_devices()`

#### 4.2 `sync_device_states` (строка 965)
- Перенести в `RouteHandlers.sync_device_states()`
- Использовать `self.plugin.state_manager.sync_states()`

#### 4.3 `auto_discover_new_devices` (строка 1016)
- Перенести в `RouteHandlers.auto_discover_new_devices()`
- Использовать `self.plugin.device_manager.discover_devices_for_user()`

#### 4.4 `handle_alice_request` (строка 1095)
- Перенести в `RouteHandlers.handle_alice_request()`
- Вспомогательные методы (`process_alice_command`, `match_intent`, `execute_intent_action`, `parse_device_command`, `execute_device_action`, `send_command_to_yandex_device`) тоже перенести

#### 4.5 `handle_alice_button` (строка 1326)
- Перенести в `RouteHandlers.handle_alice_button()`

#### 4.6 `list_intents` (строка 1361)
- Перенести в `RouteHandlers.list_intents()`

#### 4.7 `create_intent` (строка 1388)
- Перенести в `RouteHandlers.create_intent()`

#### 4.8 `update_intent` (строка 1427)
- Перенести в `RouteHandlers.update_intent()`

#### 4.9 `delete_intent` (строка 1469)
- Перенести в `RouteHandlers.delete_intent()`

#### 4.10 `list_bindings` и `create_binding` (строки 1082, 1086)
- Перенести в `RouteHandlers.list_bindings()` и `RouteHandlers.create_binding()`

---

### ШАГ 5: Обновить регистрацию роутов в main.py

**Файл**: `main.py`, метод `on_load()` (строки 74-82)

**Было**:
```python
self.router.add_api_route("/sync", self.sync_devices, methods=["POST"])
self.router.add_api_route("/sync_states", self.sync_device_states, methods=["POST"])
self.router.add_api_route("/discover", self.auto_discover_new_devices, methods=["POST"])
self.router.add_api_route("/alice", self.handle_alice_request, methods=["POST"])
self.router.add_api_route("/intents", self.list_intents, methods=["GET"])
self.router.add_api_route("/intents", self.create_intent, methods=["POST"])
```

**Станет**:
```python
self.router.add_api_route("/sync", self.route_handlers.sync_devices, methods=["POST"])
self.router.add_api_route("/sync_states", self.route_handlers.sync_device_states, methods=["POST"])
self.router.add_api_route("/discover", self.route_handlers.auto_discover_new_devices, methods=["POST"])
self.router.add_api_route("/alice", self.route_handlers.handle_alice_request, methods=["POST"])
self.router.add_api_route("/intents", self.route_handlers.list_intents, methods=["GET"])
self.router.add_api_route("/intents", self.route_handlers.create_intent, methods=["POST"])
self.router.add_api_route("/intents/{intent_name}", self.route_handlers.update_intent, methods=["PUT"])
self.router.add_api_route("/intents/{intent_name}", self.route_handlers.delete_intent, methods=["DELETE"])
self.router.add_api_route("/bindings", self.route_handlers.list_bindings, methods=["GET"])
self.router.add_api_route("/bindings", self.route_handlers.create_binding, methods=["POST"])
```

---

### ШАГ 6: Очистить main.py от перенесенных методов

**Действие**: Удалить все методы, которые были перенесены в `RouteHandlers`:
- `sync_devices`
- `sync_device_states`
- `auto_discover_new_devices`
- `handle_alice_request`
- `process_alice_command`
- `match_intent`
- `execute_intent_action`
- `parse_device_command`
- `execute_device_action`
- `send_command_to_yandex_device`
- `handle_alice_button`
- `list_intents`
- `create_intent`
- `update_intent`
- `delete_intent`
- `list_bindings`
- `create_binding`
- `_update_device_status`
- `_get_device_full_data` (если не используется)
- `_get_device_state` (если не используется)
- `_send_yandex_command` (если не используется)
- `_convert_action_to_yandex_params`
- `_map_action_to_yandex_type`

**Оставить в main.py**:
- `on_load()` - инициализация
- `on_unload()` - cleanup
- `_get_current_user_id()` - helper
- `_save_account()` - helper
- `_discover_devices_for_user()` - helper (или перенести в DeviceManager)
- `_save_user_info()` - helper
- `_get_user_access_token()` - helper
- `_handle_device_execute_event()` - event handler (если используется)

---

### ШАГ 7: Проверить и удалить старые файлы

#### 7.1 Проверить `handler.py`
- Проверить, используется ли где-то кроме `__init__.py`
- Если нет - удалить или переименовать в `handler.py.old`

#### 7.2 Проверить `api.py` и `auth.py`
- Проверить импорты: `grep -r "from.*api import\|import.*api" .`
- Если не используются - удалить

---

### ШАГ 8: Финальная проверка

#### 8.1 Синтаксис
```bash
python3 -m py_compile main.py
python3 -m py_compile handlers/routes.py
```

#### 8.2 Импорты
- Проверить, что все импорты корректны
- Убедиться, что нет циклических зависимостей

#### 8.3 Линтер
```bash
ruff check main.py handlers/routes.py
# или
flake8 main.py handlers/routes.py
```

#### 8.4 Функциональность
- OAuth flow работает
- Синхронизация устройств работает
- Команды на устройства работают
- Интенты работают

---

## 📝 Чеклист выполнения

- [ ] ШАГ 1: `__init__.py` обновлен, система использует `main.py`
- [ ] ШАГ 2: Все прямые HTTP вызовы заменены на `YandexAPIClient`
- [ ] ШАГ 3: Дублирующиеся методы удалены
- [ ] ШАГ 4: Все HTTP handlers перенесены в `RouteHandlers`
- [ ] ШАГ 5: Роуты обновлены на `self.route_handlers.*`
- [ ] ШАГ 6: Перенесенные методы удалены из `main.py`
- [ ] ШАГ 7: Старые файлы проверены и удалены
- [ ] ШАГ 8: Все проверки пройдены

---

## ⚠️ Важные замечания

1. **Делать по шагам** - не пытаться всё сразу
2. **Коммитить после каждого шага** - чтобы можно было откатиться
3. **Тестировать после каждого шага** - убедиться, что ничего не сломалось
4. **Не удалять `handler.py` сразу** - сначала убедиться, что `main.py` работает

---

## 🎯 Итоговая структура main.py

После миграции `main.py` должен содержать только:
- Импорты
- Класс `YandexSmartHomePlugin` с методами:
  - `on_load()` - инициализация менеджеров и регистрация роутов
  - `on_unload()` - cleanup
  - Helper методы для работы с пользователями и аккаунтами
  - Event handlers (если есть)

**Никакой бизнес-логики, никаких прямых HTTP вызовов!**
