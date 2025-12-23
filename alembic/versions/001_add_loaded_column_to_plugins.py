"""add loaded column to plugins

Revision ID: 001
Revises: 
Create Date: 2025-01-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Проверяем, существует ли таблица plugins
    # Если таблицы нет, создаем её сначала (для совместимости с существующими БД)
    from alembic import context
    bind = context.get_bind()
    inspector = sa.inspect(bind)
    
    if 'plugins' not in inspector.get_table_names():
        # Таблицы нет - создаем её с нужным столбцом
        op.create_table(
            'plugins',
            sa.Column('id', sa.String(128), primary_key=True),
            sa.Column('name', sa.String(128), nullable=False, unique=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('publisher', sa.String(128), nullable=True),
            sa.Column('latest_version', sa.String(64), nullable=True),
            sa.Column('loaded', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
    else:
        # Таблица существует - проверяем, есть ли уже столбец loaded
        columns = [col['name'] for col in inspector.get_columns('plugins')]
        if 'loaded' not in columns:
            # Добавляем столбец loaded в таблицу plugins
            # Используем server_default для совместимости с PostgreSQL и SQLite
            op.add_column('plugins', sa.Column('loaded', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    # Удаляем столбец loaded из таблицы plugins
    op.drop_column('plugins', 'loaded')

