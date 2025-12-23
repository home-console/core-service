from logging.config import fileConfig
from sqlalchemy import pool, create_engine
from sqlalchemy.engine import Connection
from alembic import context
import sys
import os

# Добавляем текущую директорию в path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Создаем Base напрямую, чтобы избежать импорта engine из db.py
from sqlalchemy.orm import declarative_base
Base = declarative_base()

# Импортируем модели, но они используют Base из db.py
# Нужно перехватить импорт db до того, как models.py попытается его импортировать
import importlib
import types

# Создаем фиктивный модуль db с нашим Base
# Это должно быть сделано ДО импорта models
fake_db = types.ModuleType('db')
fake_db.Base = Base
# Добавляем в sys.modules до импорта models
sys.modules['db'] = fake_db

# Также создаем фиктивный модуль для относительного импорта
core_service_dir = os.path.dirname(os.path.dirname(__file__))
if core_service_dir not in sys.path:
    sys.path.insert(0, core_service_dir)

# Создаем фиктивный пакет core_service
if 'core_service' not in sys.modules:
    core_service_pkg = types.ModuleType('core_service')
    sys.modules['core_service'] = core_service_pkg
    core_service_db = types.ModuleType('core_service.db')
    core_service_db.Base = Base
    sys.modules['core_service.db'] = core_service_db

# Теперь импортируем модели - они будут использовать наш Base
try:
    from models import Device, Plugin, PluginVersion, PluginBinding, IntentMapping, PluginInstallJob
except ImportError as e:
    # Если не получается, просто используем Base.metadata
    # Модели уже определены в Base.metadata через импорт
    pass

# Импортируем модели из плагинов (если доступны)
try:
    from plugins.client_manager.models import Client, CommandLog, Enrollment, TerminalAudit
except ImportError:
    pass

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def get_url():
    """Получить URL БД для миграций (синхронный формат)."""
    # Получаем URL из переменной окружения
    url = os.getenv("CORE_DB_URL")
    
    if not url:
        # По умолчанию SQLite в текущей директории
        db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core_admin.db")
        url = f"sqlite:///{db_path}"
    
    # Конвертируем async URL в sync для Alembic
    if url.startswith("sqlite+aiosqlite:///"):
        url = url.replace("sqlite+aiosqlite:///", "sqlite:///")
    elif url.startswith("sqlite:///"):
        # Уже правильный формат
        pass
    elif url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://")
    elif url.startswith("postgresql://"):
        # Уже правильный формат
        pass
    
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = get_url()
    
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.
    
    Используем синхронный engine для всех БД, так как Alembic работает синхронно.
    """
    url = get_url()
    
    # Для миграций всегда используем синхронный engine
    # Конвертируем URL в синхронный формат если нужно
    sync_url = url
    
    # Убеждаемся, что URL в синхронном формате
    if sync_url.startswith("postgresql+asyncpg://"):
        sync_url = sync_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    elif sync_url.startswith("postgresql://"):
        # Если нет драйвера, добавляем psycopg2
        if "+" not in sync_url.split("://")[1].split("@")[0]:
            sync_url = sync_url.replace("postgresql://", "postgresql+psycopg2://")
    
    connectable = create_engine(sync_url, poolclass=pool.NullPool)
    
    with connectable.connect() as connection:
        do_run_migrations(connection)
    
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

