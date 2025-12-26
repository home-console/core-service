"""Add device status fields: is_online, is_on, last_seen, updated_at

Revision ID: 005
Revises: 004
Create Date: 2025-12-24 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from datetime import datetime


# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add status tracking columns to devices table."""
    from alembic import context
    bind = context.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    
    if 'devices' in tables:
        columns = [c['name'] for c in inspector.get_columns('devices')]
        
        # Добавляем колонку is_online (Boolean) если её нет
        if 'is_online' not in columns:
            op.add_column('devices', sa.Column('is_online', sa.Boolean(), nullable=False, server_default=sa.false()))
        
        # Добавляем колонку is_on (Boolean) если её нет
        if 'is_on' not in columns:
            op.add_column('devices', sa.Column('is_on', sa.Boolean(), nullable=False, server_default=sa.false()))
        
        # Добавляем колонку last_seen (DateTime) если её нет
        if 'last_seen' not in columns:
            op.add_column('devices', sa.Column('last_seen', sa.DateTime(), nullable=True))
        
        # Добавляем колонку updated_at (DateTime) если её нет
        if 'updated_at' not in columns:
            op.add_column('devices', sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()))


def downgrade() -> None:
    """Remove status tracking columns from devices table."""
    from alembic import context
    bind = context.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    
    if 'devices' in tables:
        columns = [c['name'] for c in inspector.get_columns('devices')]
        
        if 'updated_at' in columns:
            op.drop_column('devices', 'updated_at')
        if 'last_seen' in columns:
            op.drop_column('devices', 'last_seen')
        if 'is_on' in columns:
            op.drop_column('devices', 'is_on')
        if 'is_online' in columns:
            op.drop_column('devices', 'is_online')
