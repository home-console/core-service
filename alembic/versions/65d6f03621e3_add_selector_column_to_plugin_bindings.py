"""add_selector_column_to_plugin_bindings

Revision ID: 65d6f03621e3
Revises: c777eb838455
Create Date: 2025-12-24 08:27:28.399893

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '65d6f03621e3'
down_revision: Union[str, None] = 'c777eb838455'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add selector (String) column to plugin_bindings table."""
    from alembic import context
    bind = context.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    
    if 'plugin_bindings' in tables:
        columns = [c['name'] for c in inspector.get_columns('plugin_bindings')]
        
        # Добавляем колонку selector (String) если её нет
        if 'selector' not in columns:
            op.add_column('plugin_bindings', sa.Column('selector', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Remove selector column from plugin_bindings table."""
    from alembic import context
    bind = context.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    
    if 'plugin_bindings' in tables:
        columns = [c['name'] for c in inspector.get_columns('plugin_bindings')]
        
        if 'selector' in columns:
            op.drop_column('plugin_bindings', 'selector')

