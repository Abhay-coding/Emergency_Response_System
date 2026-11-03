"""Initial schema

Revision ID: 20261103_120000
Revises:
Create Date: 2026-11-03 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20261103_120000'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('role', sa.Enum('reporter', 'responder', 'admin', name='role'), nullable=False, server_default='reporter'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_role'), 'users', ['role'], unique=False)
    op.create_index(op.f('ix_users_created_at'), 'users', ['created_at'], unique=False)

    # Create incidents table
    op.create_table(
        'incidents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=150), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('location', sa.String(length=200), nullable=False),
        sa.Column('priority', sa.Enum('low', 'medium', 'high', 'critical', name='incidentpriority'), nullable=False, server_default='medium'),
        sa.Column('status', sa.Enum('reported', 'assigned', 'in_progress', 'resolved', name='incidentstatus'), nullable=False, server_default='reported'),
        sa.Column('reporter_id', sa.Integer(), nullable=False),
        sa.Column('assigned_to', sa.Integer(), nullable=True),
        sa.Column('image_path', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reporter_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_incidents_category'), 'incidents', ['category'], unique=False)
    op.create_index(op.f('ix_incidents_priority'), 'incidents', ['priority'], unique=False)
    op.create_index(op.f('ix_incidents_status'), 'incidents', ['status'], unique=False)
    op.create_index(op.f('ix_incidents_reporter_id'), 'incidents', ['reporter_id'], unique=False)
    op.create_index(op.f('ix_incidents_assigned_to'), 'incidents', ['assigned_to'], unique=False)
    op.create_index(op.f('ix_incidents_created_at'), 'incidents', ['created_at'], unique=False)

    # Create token_families table
    op.create_table(
        'token_families',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('family_id', sa.String(length=64), nullable=False),
        sa.Column('current_jti', sa.String(length=64), nullable=True),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('family_id')
    )
    op.create_index(op.f('ix_token_families_user_id'), 'token_families', ['user_id'], unique=False)
    op.create_index(op.f('ix_token_families_family_id'), 'token_families', ['family_id'], unique=True)
    op.create_index(op.f('ix_token_families_revoked'), 'token_families', ['revoked'], unique=False)
    op.create_index('ix_token_families_user_revoked', 'token_families', ['user_id', 'revoked'], unique=False)
    op.create_index('ix_token_families_family_revoked', 'token_families', ['family_id', 'revoked'], unique=False)


def downgrade() -> None:
    op.drop_table('token_families')
    op.drop_table('incidents')
    op.drop_table('users')