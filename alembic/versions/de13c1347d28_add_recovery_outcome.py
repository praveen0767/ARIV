"""add_recovery_outcome

Revision ID: de13c1347d28
Revises: add_outbox_lifecycle_and_lease
Create Date: 2026-09-03 19:04:50.186606

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'de13c1347d28'
down_revision: Union[str, Sequence[str], None] = 'add_outbox_lifecycle_and_lease'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Let sa.Enum handle type creation
    op.create_table(
        'recovery_outcome',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('case_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('action_id', sa.UUID(), nullable=True),
        sa.Column('outcome_status', sa.Enum('PENDING', 'RECOVERED', 'PARTIALLY_RECOVERED', 'FAILED', 'EXPIRED', 'UNKNOWN', 'NO_RECOVERY', name='recovery_outcome_status'), nullable=False),
        sa.Column('recovered_amount', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('recovered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('provider_reference', sa.String(), nullable=True),
        sa.Column('time_to_recovery', sa.Interval(), nullable=True),
        sa.Column('recovery_source', sa.Enum('ACTION_ATTRIBUTED', 'ORGANIC_RECOVERY', 'BASELINE_RECOVERY', 'UNKNOWN_ATTRIBUTION', name='recovery_source_type'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['action_id'], ['action.id'], ),
        sa.ForeignKeyConstraint(['case_id'], ['recovery_case.id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('recovery_outcome')
    op.execute("DROP TYPE recovery_source_type")
    op.execute("DROP TYPE recovery_outcome_status")
