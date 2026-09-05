'''Revision ID: add_action_table
Revises: None
Create Date: 2026-09-03 22:56:40.000000
'''

from alembic import op
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg

# revision identifiers, used by Alembic.
revision = 'add_action_table'
down_revision = '20260903_00_initial_schema'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'action',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('case_id', pg.UUID(as_uuid=True), sa.ForeignKey('recovery_case.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', pg.UUID(as_uuid=True), sa.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False),
        sa.Column('decision_id', pg.UUID(as_uuid=True), sa.ForeignKey('decision_record.id', ondelete='CASCADE'), nullable=False),
        sa.Column('action_type', sa.Enum('RETRY_NOW', 'RETRY_LATER', 'REQUEST_PAYMENT_METHOD_UPDATE', 'GENERATE_PAYMENT_LINK', 'SEND_REMINDER', 'ESCALATE_TO_HUMAN', 'WAIT', 'STOP_RECOVERY', name='recoveryaction'), nullable=False),
        sa.Column('status', sa.Enum('PROPOSED', 'AUTHORIZED', 'QUEUED', 'EXECUTING', 'SUCCEEDED', 'FAILED', 'UNKNOWN', 'CANCELLED', 'SUPERSEDED', name='actionstatus'), nullable=False, server_default='PROPOSED'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_action_unique', 'action', ['tenant_id', 'case_id', 'action_type', 'decision_id'], unique=True)

def downgrade():
    op.drop_index('ix_action_unique', table_name='action')
    op.drop_table('action')
