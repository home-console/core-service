# Core Service

Основной сервис системы управления умным домом.

## 📁 Структура проекта

```
core-service/
├── app.py              # Главный файл приложения (FastAPI)
├── main.py             # Точка входа
├── asgi.py             # ASGI приложение
├── plugin_loader.py    # Реэкспорт PluginLoader (обратная совместимость)
│
├── core/               # Основные модули
│   ├── database/       # БД и модели
│   │   ├── db.py       # Настройка БД
│   │   └── models.py   # SQLAlchemy модели
│   ├── event_bus.py    # Event Bus для межплагинного взаимодействия
│   ├── dependencies.py # Dependency Injection функции
│   ├── constants.py    # Константы
│   └── health_monitor.py # Мониторинг здоровья сервисов
│
├── alembic/            # Миграции БД (Alembic)
├── docs/               # Документация
├── plugin_system/      # Система плагинов
├── plugins/            # Встроенные плагины
├── routes/             # API маршруты
├── scripts/            # Утилиты и скрипты
├── services/           # Сервисы (Orchestrator, ManagedService)
├── static/             # Статические файлы
├── tests/              # Тесты
└── utils/              # Утилиты
```

## 🚀 Быстрый старт

```bash
# Установка зависимостей
pip install -r requirements.txt

# Запуск
python main.py
```

## 📚 Документация

Вся документация находится в директории [`docs/`](./docs/):

- [README.md](./docs/README.md) - Обзор документации
- [CRITICAL_ISSUES.md](./docs/CRITICAL_ISSUES.md) - Критические проблемы и решения
- [DEVELOPER_EXPERIENCE.md](./docs/DEVELOPER_EXPERIENCE.md) - Developer Experience
- [OPTIMIZATIONS.md](./docs/OPTIMIZATIONS.md) - Оптимизации производительности

## 🔌 Плагины

Плагины находятся в директории `plugins/`. Система плагинов описана в `plugin_system/`.

## 🛠️ Разработка

См. [DEVELOPER_EXPERIENCE.md](./docs/DEVELOPER_EXPERIENCE.md) для подробностей о разработке и поддержке проекта.

