"""add_recovery_measurement

Revision ID: f2f823684ccd
Revises: 503469c3ba78
Create Date: 2026-09-03 19:05:45.176554

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2f823684ccd'
down_revision: Union[str, Sequence[str], None] = '503469c3ba78'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'recovery_measurement',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('outcome_id', sa.UUID(), nullable=False),
        sa.Column('measurement_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('estimated_control_recovery', sa.Integer(), nullable=True),
        sa.Column('treatment_recovery', sa.Integer(), nullable=False),
        sa.Column('incremental_recovery', sa.Integer(), nullable=False),
        sa.Column('cost_of_recovery', sa.Integer(), nullable=True),
        sa.Column('attribution_window_seconds', sa.Integer(), nullable=False),
        sa.Column('experiment_id', sa.UUID(), nullable=True),
        sa.Column('baseline_policy_version', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['experiment_id'], ['experiment.id'], ),
        sa.ForeignKeyConstraint(['outcome_id'], ['recovery_outcome.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('recovery_measurement')
