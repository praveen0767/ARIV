"""add_experiment

Revision ID: 503469c3ba78
Revises: de13c1347d28
Create Date: 2026-09-03 19:06:20.309721

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '503469c3ba78'
down_revision: Union[str, Sequence[str], None] = 'de13c1347d28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Let sa.Enum handle type creation
    op.create_table(
        'experiment',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('status', sa.Enum('DRAFT', 'ACTIVE', 'COMPLETED', 'PAUSED', name='experiment_status'), nullable=False),
        sa.Column('treatment_policy', sa.JSON(), nullable=False),
        sa.Column('control_policy', sa.JSON(), nullable=False),
        sa.Column('allocation_percentage', sa.Integer(), nullable=False),
        sa.Column('metric_definition', sa.JSON(), nullable=False),
        sa.Column('start_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('policy_version', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('experiment')
    op.execute("DROP TYPE experiment_status")
