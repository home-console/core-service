# Alembic Migrations

## Использование

### Применить все миграции
```bash
alembic upgrade head
```

### Откатить последнюю миграцию
```bash
alembic downgrade -1
```

### Создать новую миграцию (автогенерация)
```bash
alembic revision --autogenerate -m "описание изменений"
```

### Создать пустую миграцию
```bash
alembic revision -m "описание изменений"
```

### Просмотр текущей версии
```bash
alembic current
```

### История миграций
```bash
alembic history
```

## В Docker

### Вариант 1: Запуск миграций внутри контейнера (рекомендуется)
```bash
# Запустить миграции внутри контейнера core
docker-compose exec core alembic upgrade head

# Или если контейнер еще не запущен
docker-compose run --rm core alembic upgrade head
```

### Вариант 2: Локально (если PostgreSQL доступен)
Если нужно запускать миграции локально, нужно:
1. Экспортировать порт PostgreSQL в docker-compose.yml
2. Использовать правильный URL:
```bash
export CORE_DB_URL="postgresql://home:homepass@localhost:5432/home_console"
alembic upgrade head
```

