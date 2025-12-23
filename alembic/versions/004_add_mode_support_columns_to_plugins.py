"""add supported_modes and mode_switch_supported columns to plugins

Revision ID: 004
Revises: 003
Create Date: 2025-01-27 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add supported_modes (JSON) and mode_switch_supported (Boolean) columns to plugins table."""
    from alembic import context
    bind = context.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    
    if 'plugins' in tables:
        columns = [c['name'] for c in inspector.get_columns('plugins')]
        
        # Добавляем колонку supported_modes (JSON) если её нет
        if 'supported_modes' not in columns:
            op.add_column('plugins', sa.Column('supported_modes', sa.JSON(), nullable=True))
        
        # Добавляем колонку mode_switch_supported (Boolean) если её нет
        if 'mode_switch_supported' not in columns:
            op.add_column('plugins', sa.Column('mode_switch_supported', sa.Boolean(), nullable=True, server_default=sa.false()))


def downgrade() -> None:
    """Remove supported_modes and mode_switch_supported columns from plugins table."""
    from alembic import context
    bind = context.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    
    if 'plugins' in tables:
        columns = [c['name'] for c in inspector.get_columns('plugins')]
        
        if 'mode_switch_supported' in columns:
            op.drop_column('plugins', 'mode_switch_supported')
        
        if 'supported_modes' in columns:
            op.drop_column('plugins', 'supported_modes')
