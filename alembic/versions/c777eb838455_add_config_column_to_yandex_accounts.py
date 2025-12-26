"""add_config_column_to_yandex_accounts

Revision ID: c777eb838455
Revises: 004
Create Date: 2025-12-24 08:20:23.744578

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c777eb838455'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add config (JSON) column to yandex_accounts table."""
    from alembic import context
    bind = context.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    
    if 'yandex_accounts' in tables:
        columns = [c['name'] for c in inspector.get_columns('yandex_accounts')]
        
        # Добавляем колонку config (JSON) если её нет
        if 'config' not in columns:
            op.add_column('yandex_accounts', sa.Column('config', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove config column from yandex_accounts table."""
    from alembic import context
    bind = context.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    
    if 'yandex_accounts' in tables:
        columns = [c['name'] for c in inspector.get_columns('yandex_accounts')]
        
        if 'config' in columns:
            op.drop_column('yandex_accounts', 'config')

