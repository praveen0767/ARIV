"""measurement_semantics_hardening

Revision ID: 20260904_07
Revises: 20260904_06
Create Date: 2026-09-04 14:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260904_07'
down_revision: Union[str, Sequence[str], None] = '20260904_06'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. RecoveryMeasurement: add control_recovery, baseline_method, provenance, is_counterfactual_estimate
    op.add_column('recovery_measurement', sa.Column('control_recovery', sa.Integer(), server_default='0', nullable=False))
    op.add_column('recovery_measurement', sa.Column('baseline_method', sa.String(), server_default='deterministic_heuristic', nullable=True))
    op.add_column('recovery_measurement', sa.Column('provenance', sa.String(), nullable=True))
    op.add_column('recovery_measurement', sa.Column('is_counterfactual_estimate', sa.Boolean(), server_default='true', nullable=True))

    # 2. BaselineDecision: add baseline_method, provenance, is_estimate
    op.add_column('baseline_decision', sa.Column('baseline_method', sa.String(), server_default='deterministic_heuristic', nullable=True))
    op.add_column('baseline_decision', sa.Column('provenance', sa.String(), nullable=True))
    op.add_column('baseline_decision', sa.Column('is_estimate', sa.Boolean(), server_default='true', nullable=True))

    # 3. RecoveryOutcome: add attribution_decision, attribution_provenance
    op.add_column('recovery_outcome', sa.Column('attribution_decision', sa.String(), nullable=True))
    op.add_column('recovery_outcome', sa.Column('attribution_provenance', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('recovery_outcome', 'attribution_provenance')
    op.drop_column('recovery_outcome', 'attribution_decision')
    op.drop_column('baseline_decision', 'is_estimate')
    op.drop_column('baseline_decision', 'provenance')
    op.drop_column('baseline_decision', 'baseline_method')
    op.drop_column('recovery_measurement', 'is_counterfactual_estimate')
    op.drop_column('recovery_measurement', 'provenance')
    op.drop_column('recovery_measurement', 'baseline_method')
    op.drop_column('recovery_measurement', 'control_recovery')
