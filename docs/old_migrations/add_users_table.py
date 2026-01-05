"""
Database migration to add User table for authentication.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


def upgrade():
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.String(128), primary_key=True),
        sa.Column('username', sa.String(64), unique=True, index=True, nullable=False),
        sa.Column('email', sa.String(128), unique=True, index=True, nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('role', sa.String(32), server_default='user', nullable=False),
        sa.Column('enabled', sa.Boolean, server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime, server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('last_login', sa.DateTime),
        sa.Column('last_activity', sa.DateTime),
        sa.Column('metadata', postgresql.JSONB, nullable=True)
    )
    
    # Create indexes
    op.create_index('ix_users_username', 'users', ['username'])
    op.create_index('ix_users_email', 'users', ['email'])


def downgrade():
    op.drop_table('users')