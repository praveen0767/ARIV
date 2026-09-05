"""add_baseline_decision

Revision ID: 24f14e1d95bb
Revises: f2f823684ccd
Create Date: 2026-09-03 19:06:46.047640

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '24f14e1d95bb'
down_revision: Union[str, Sequence[str], None] = 'f2f823684ccd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'baseline_decision',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('case_id', sa.UUID(), nullable=False),
        sa.Column('baseline_action', sa.Enum(name='recoveryaction', create_type=False), nullable=False),
        sa.Column('policy_version', sa.String(), nullable=False),
        sa.Column('expected_recovery_amount', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['recovery_case.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('baseline_decision')
