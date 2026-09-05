'''Revision ID: add_outbox_lifecycle_and_lease
Revises: add_system_settings
Create Date: 2026-09-04 00:00:00.000000

Adds outbox lifecycle status (PENDING, CLAIMED, COMPLETED, FAILED, DEAD_LETTERED),
worker leasing columns (claimed_at, claimed_by, lease_expires_at), attempt tracking,
and indexing for durable concurrency control.
'''

from alembic import op
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg

# revision identifiers, used by Alembic.
revision = 'add_outbox_lifecycle_and_lease'
down_revision = 'add_system_settings'
branch_labels = None
depends_on = None

outbox_status_enum = sa.Enum('PENDING', 'CLAIMED', 'COMPLETED', 'FAILED', 'DEAD_LETTERED', name='outboxstatus')


def upgrade():
    # 1. Create OutboxStatus enum type
    outbox_status_enum.create(op.get_bind(), checkfirst=True)

    # 2. Add columns to execution_outbox table
    op.add_column(
        'execution_outbox',
        sa.Column('status', outbox_status_enum, nullable=False, server_default='PENDING')
    )
    op.add_column(
        'execution_outbox',
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        'execution_outbox',
        sa.Column('claimed_by', sa.String(length=255), nullable=True)
    )
    op.add_column(
        'execution_outbox',
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        'execution_outbox',
        sa.Column('attempt_count', sa.Integer, nullable=False, server_default='0')
    )
    op.add_column(
        'execution_outbox',
        sa.Column('max_retries', sa.Integer, nullable=False, server_default='3')
    )
    op.add_column(
        'execution_outbox',
        sa.Column('last_error', sa.String, nullable=True)
    )

    # 3. Create index for efficient claiming of PENDING and expired CLAIMED rows
    op.create_index(
        'ix_execution_outbox_status_lease',
        'execution_outbox',
        ['status', 'lease_expires_at']
    )


def downgrade():
    op.drop_index('ix_execution_outbox_status_lease', table_name='execution_outbox')
    op.drop_column('execution_outbox', 'last_error')
    op.drop_column('execution_outbox', 'max_retries')
    op.drop_column('execution_outbox', 'attempt_count')
    op.drop_column('execution_outbox', 'lease_expires_at')
    op.drop_column('execution_outbox', 'claimed_by')
    op.drop_column('execution_outbox', 'claimed_at')
    op.drop_column('execution_outbox', 'status')
    outbox_status_enum.drop(op.get_bind(), checkfirst=True)
