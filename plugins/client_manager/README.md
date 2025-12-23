# Client Manager Plugin

Внутренний плагин для управления клиентами, файлами и регистрациями.

## 🔄 Режимы работы

Плагин поддерживает **два режима**:

| Режим | Переменная | Описание |
|-------|------------|----------|
| **microservice** | `CM_MODE=external` | Отдельный Docker контейнер (production) |
| **in_process** | `CM_MODE=embedded` | Subprocess внутри Core (development) |

### Управление через API

```bash
# Получить текущий режим
curl http://localhost:11000/api/plugins/client_manager/mode

# Изменить режим на embedded (in_process)
curl -X POST http://localhost:11000/api/plugins/client_manager/mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "in_process", "apply_now": true}'

# Изменить режим на external (microservice)
curl -X POST http://localhost:11000/api/plugins/client_manager/mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "microservice", "apply_now": true}'

# Список всех плагинов с режимами
curl http://localhost:11000/api/plugins/modes
```

### Управление через переменные окружения

```bash
# External mode (default, production)
CM_MODE=external
CM_BASE_URL=http://client_manager:10000

# Embedded mode (development)
CM_MODE=embedded
CM_BASE_URL=http://127.0.0.1:10000
```

## Функциональность

### Управление клиентами
- `GET /api/clients` - список подключенных клиентов
- `POST /api/commands/{client_id}` - выполнение команд на клиенте
- `POST /api/commands/{client_id}/cancel` - отмена команды
- `GET /api/commands/history` - история команд
- `GET /api/commands/{command_id}` - результат команды
- `POST /api/clients/{client_id}/install` - установка сервисов на агенте

### Управление файлами
- `POST /api/files/upload` - загрузка файла на клиента
- `POST /api/files/download` - инициирование скачивания файла
- `GET /api/files/download/{transfer_id}` - скачивание файла
- `GET /api/files/transfers/{transfer_id}/status` - статус трансфера
- `POST /api/files/transfers/pause` - пауза трансфера
- `POST /api/files/transfers/resume` - возобновление трансфера
- `POST /api/files/transfers/cancel` - отмена трансфера

### Регистрация клиентов (TOFU)
- `GET /api/enrollments/pending` - список ожидающих регистрации клиентов
- `POST /api/enrollments/{client_id}/approve` - одобрить регистрацию
- `POST /api/enrollments/{client_id}/reject` - отклонить регистрацию

### Терминальный аудит
- `POST /api/terminals/audit` - создание/обновление записи аудита терминальной сессии

## Модели данных

- `Client` - информация о подключенных клиентах
- `CommandLog` - история выполнения команд
- `Enrollment` - регистрация клиентов (TOFU)
- `TerminalAudit` - аудит терминальных сессий

## Зависимости

Плагин взаимодействует с внешним `client-manager-service` через HTTP API.
Требует настройки переменных окружения:
- `CM_BASE_URL` - базовый URL client-manager-service (по умолчанию `http://127.0.0.1:10000`)
- `ADMIN_TOKEN` или `ADMIN_JWT_SECRET` - для аутентификации при admin операциях

## Интеграция: встроенный vs внешний режим

- `CM_MODE`: `embedded` или `external` (по умолчанию `external`).
	- `embedded` — при загрузке плагина ядро попытается запустить `client-manager-service/run_server.py` как subprocess и направлять запросы на `http://127.0.0.1:10000`.
	- `external` — плагин будет проксировать запросы на `CM_BASE_URL` (обычное поведение).

Пример переменных окружения для `embedded`:

```
CM_MODE=embedded
# опционально
CM_BASE_URL=http://127.0.0.1:10000
ADMIN_TOKEN=...
```

Пример docker-compose (внешний сервис):

```yaml
services:
	core:
		image: home-console-core:latest
		environment:
			- CM_MODE=external
			- CM_BASE_URL=http://client-manager:10000
	client-manager:
		image: client-manager:latest
		ports:
			- 10000:10000
```

Пример для запуска в одном контейнере (встроенный режим внутри Core не рекомендуется в production):

```yaml
services:
	core:
		image: home-console-core:latest
		environment:
			- CM_MODE=embedded
```

