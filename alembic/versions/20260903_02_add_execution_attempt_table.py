'''Revision ID: add_execution_attempt_table
Revises: add_action_table
Create Date: 2026-09-03 22:57:10.000000
'''

from alembic import op
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg

# revision identifiers, used by Alembic.
revision = 'add_execution_attempt_table'
down_revision = 'add_action_table'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'execution_attempt',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('action_id', pg.UUID(as_uuid=True), sa.ForeignKey('action.id', ondelete='CASCADE'), nullable=False),
        sa.Column('attempt_number', sa.Integer, nullable=False),
        sa.Column('status', sa.Enum('EXECUTING', 'SUCCEEDED', 'FAILED', 'UNKNOWN', name='executionstatus'), nullable=False),
        sa.Column('provider_request_id', sa.String, nullable=True),
        sa.Column('metadata', sa.JSON, nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_execution_attempt_unique', 'execution_attempt', ['action_id', 'attempt_number'], unique=True)

def downgrade():
    op.drop_index('ix_execution_attempt_unique', table_name='execution_attempt')
    op.drop_table('execution_attempt')
