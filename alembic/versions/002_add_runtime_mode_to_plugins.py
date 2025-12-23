"""add runtime_mode column to plugins

Revision ID: 002
Revises: 001
Create Date: 2025-01-27 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = 'f84ed814b1b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Проверяем, существует ли таблица plugins
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
            sa.Column('runtime_mode', sa.String(32), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
    else:
        # Таблица существует - проверяем, есть ли уже столбец runtime_mode
        columns = [col['name'] for col in inspector.get_columns('plugins')]
        if 'runtime_mode' not in columns:
            # Добавляем столбец runtime_mode в таблицу plugins
            op.add_column('plugins', sa.Column('runtime_mode', sa.String(32), nullable=True))


def downgrade() -> None:
    # Удаляем столбец runtime_mode из таблицы plugins
    from alembic import context
    bind = context.get_bind()
    inspector = sa.inspect(bind)
    
    if 'plugins' in inspector.get_table_names():
        columns = [col['name'] for col in inspector.get_columns('plugins')]
        if 'runtime_mode' in columns:
            op.drop_column('plugins', 'runtime_mode')

