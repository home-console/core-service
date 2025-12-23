from __future__ import annotations

import os
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

# Base для моделей (используется в models.py)
Base = declarative_base()

DB_URL = os.getenv("CORE_DB_URL", f"sqlite:///" + os.path.join(os.path.dirname(__file__), "core_admin.db"))

# Конвертируем SQLite URL в async версию
if DB_URL.startswith("sqlite:///"):
    # Для SQLite используем aiosqlite
    async_db_url = DB_URL.replace("sqlite:///", "sqlite+aiosqlite:///")
elif DB_URL.startswith("postgresql://"):
    # Для PostgreSQL используем asyncpg
    async_db_url = DB_URL.replace("postgresql://", "postgresql+asyncpg://")
elif DB_URL.startswith("postgresql+psycopg2://"):
    async_db_url = DB_URL.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
else:
    async_db_url = DB_URL

# Создаем async engine
engine = create_async_engine(
    async_db_url,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False} if async_db_url.startswith("sqlite") else {},
)

# Создаем async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """
    Async context manager для получения сессии БД.
    
    Использование:
        async with get_session() as db:
            result = await db.execute(select(Client))
            clients = result.scalars().all()
    
    Автоматически коммитит транзакцию при успехе или откатывает при ошибке.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Database error: {e}", exc_info=True)
            raise
        except Exception as e:
            await session.rollback()
            logger.error(f"Unexpected error in database session: {e}", exc_info=True)
            raise


