# Home Console – Runtime Architecture

Home Console — это runtime-платформа, где Core управляет
HTTP, жизненным циклом плагинов и системными сервисами.

Ключевой принцип:
- Core владеет процессом и FastAPI
- Плагины расширяют Core, но не управляют сервером

## Entry Points

### Production / Docker
- docker-compose.yml
- uvicorn core_service.asgi:app

### ASGI
- core_service/asgi.py импортирует app из core_service/app.py

### Runtime lifecycle
- FastAPI создаётся в app.py
- lifespan() управляет:
  - БД
  - EventBus
  - PluginLoader

## Core Runtime

Core Runtime — это:
- один ASGI/FastAPI процесс
- один EventBus
- один PluginLoader
- одна ServiceRegistry (логическая)

Core отвечает за:
- HTTP (FastAPI)
- lifecycle плагинов
- базу данных
- безопасность и конфигурацию

## Role of FastAPI

FastAPI является HTTP-адаптером Core Runtime.

ВАЖНО:
- FastAPI создаётся ТОЛЬКО в Core
- uvicorn запускается ТОЛЬКО Core
- Плагины НЕ поднимают свои FastAPI серверы

In-process plugin:
- возвращает APIRouter
- Core монтирует router через include_router()

External plugin / microservice:
- поднимает собственный FastAPI
- интегрируется через HTTP / proxy

## In-Process Plugins

In-process plugin:
- живёт в процессе Core
- реализует InternalPluginBase
- управляется PluginLoader

Lifecycle:
- on_load()
- router registration (APIRouter)
- on_unload()

Ограничения:
- плагин не запускает uvicorn
- плагин не владеет портами
- плагин не создаёт FastAPI app

## External Services (Microservices)

External service:
- отдельный процесс / контейнер
- собственный FastAPI + uvicorn
- не является in-process плагином

Пример:
client-manager-service — внешний сервис
client_manager (плагин в Core) — адаптер/прокси

## PluginLoader
PluginLoader — фактический менеджер плагинов.

Он:
- находит плагины
- создаёт экземпляры
- вызывает on_load()
- монтирует APIRouter в Core FastAPI

LifecycleManager и ModeManager — вспомогательные компоненты,
но загрузка происходит через PluginLoader.

## Non-Goals (Current Revision)

В текущей ревизии НЕ поддерживается:
- самостоятельный FastAPI внутри in-process плагина
- distributed lifecycle
- plugin sandboxing
- remote plugins как first-class citizens

## Roadmap Direction

Следующие крупные направления:
- System Plugins (automation, auth, rules)
- Чёткое разделение Adapter / Plugin / Service
- Event-driven architecture поверх EventBus

## Проверка соответствия репозиторию

Я просканировал репозиторий на предмет запуска `FastAPI`/`uvicorn` внутри in-process плагинов и других запрещённых паттернов.

- Вывод: `Core` действительно является единственным процессом, создающим `FastAPI` и запускаемым через `uvicorn` (см. `core-service/app.py`).
- `PluginLoader` в `core-service/plugin_system/loader.py` — владелец жизненного цикла плагинов (создание экземпляров, `on_load`/`on_unload`, монтирование роутеров через `include_router`).
- In-process плагины реализуют `InternalPluginBase` и возвращают `APIRouter` (пример: `example_external_plugin/main.py`) — они не поднимают свои серверы.
- В репозитории есть явные external-сервисы (например, `auth-service`, `client-manager-service`), которые запускают свои FastAPI/uvicorn — это корректно и ожидаемо для внешних адаптеров.
- В репо присутствует SDK (`sdk/python/home_console_sdk`) — это библиотека для разработки плагинов, её наличие допустимо, но важно отличать SDK от in-process плагинов.

Если нужно, можно добавить CI-проверку, которая запрещает появление `uvicorn` или `FastAPI()` в директориях плагинов (`core-service/plugins/**` и `PLUGINS_DIR`).