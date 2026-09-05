"""add_knowledge_outbox_and_idempotency

Revision ID: 20260904_06
Revises: 8c7cccd2f6ba
Create Date: 2026-09-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20260904_06'
down_revision: Union[str, Sequence[str], None] = '8c7cccd2f6ba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add amount_minor to recovery_case (additive, backward compatible)
    op.add_column('recovery_case', sa.Column('amount_minor', sa.Integer(), nullable=True))

    # 2. Add experiment_variant to recovery_measurement
    op.add_column('recovery_measurement', sa.Column('experiment_variant', sa.String(length=20), nullable=True))

    # 3. Add unique constraint on recovery_measurement.outcome_id for idempotency
    op.create_unique_constraint('uq_recovery_measurement_outcome_id', 'recovery_measurement', ['outcome_id'])

    op.create_table(
        'knowledge_outbox',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('measurement_id', sa.UUID(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('status', sa.Enum('PENDING', 'CLAIMED', 'COMPLETED', 'FAILED', 'DEAD_LETTERED', name='knowledgeoutboxstatus'), server_default='PENDING', nullable=False),
        sa.Column('attempt_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('max_retries', sa.Integer(), server_default='3', nullable=False),
        sa.Column('last_error', sa.String(), nullable=True),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('claimed_by', sa.String(length=255), nullable=True),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['measurement_id'], ['recovery_measurement.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('measurement_id', name='uq_knowledge_outbox_measurement_id')
    )

    op.create_index('ix_knowledge_outbox_status_lease', 'knowledge_outbox', ['status', 'lease_expires_at'], unique=False)
    op.create_index('ix_knowledge_outbox_tenant', 'knowledge_outbox', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_knowledge_outbox_tenant', table_name='knowledge_outbox')
    op.drop_index('ix_knowledge_outbox_status_lease', table_name='knowledge_outbox')
    op.drop_table('knowledge_outbox')
    op.execute("DROP TYPE IF EXISTS knowledgeoutboxstatus")
    op.drop_constraint('uq_recovery_measurement_outcome_id', 'recovery_measurement', type_='unique')
    op.drop_column('recovery_measurement', 'experiment_variant')
    op.drop_column('recovery_case', 'amount_minor')
