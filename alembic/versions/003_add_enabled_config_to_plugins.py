"""add enabled and config columns to plugins

Revision ID: 003
Revises: 002
Create Date: 2025-01-27 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Добавляем колонки enabled и config, если их нет
    from alembic import context
    bind = context.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if 'plugins' in tables:
        columns = [c['name'] for c in inspector.get_columns('plugins')]
        if 'enabled' not in columns:
            op.add_column('plugins', sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()))
        if 'config' not in columns:
            op.add_column('plugins', sa.Column('config', sa.JSON(), nullable=True))
        # Если нет runtime_mode (на всякий случай), добавим
        if 'runtime_mode' not in columns:
            op.add_column('plugins', sa.Column('runtime_mode', sa.String(length=32), nullable=True))
    else:
        # Таблицы нет — создаем с нужными колонками (редкий случай)
        op.create_table(
            'plugins',
            sa.Column('id', sa.String(128), primary_key=True),
            sa.Column('name', sa.String(128), nullable=False, unique=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('publisher', sa.String(128), nullable=True),
            sa.Column('latest_version', sa.String(64), nullable=True),
            sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('loaded', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('runtime_mode', sa.String(32), nullable=True),
            sa.Column('config', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    # Удаляем добавленные колонки, если они есть
    from alembic import context
    bind = context.get_bind()
    inspector = sa.inspect(bind)
    if 'plugins' in inspector.get_table_names():
        columns = [c['name'] for c in inspector.get_columns('plugins')]
        if 'enabled' in columns:
            op.drop_column('plugins', 'enabled')
        if 'config' in columns:
            op.drop_column('plugins', 'config')
        # runtime_mode оставляем, т.к. могла быть раньше

