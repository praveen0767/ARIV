'''Revision ID: add_execution_outbox_table
Revises: add_execution_attempt_table
Create Date: 2026-09-03 22:57:30.000000
'''

from alembic import op
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg

# revision identifiers, used by Alembic.
revision = 'add_execution_outbox_table'
down_revision = 'add_execution_attempt_table'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'execution_outbox',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('action_id', pg.UUID(as_uuid=True), sa.ForeignKey('action.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('payload', sa.JSON, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('dispatched', sa.Boolean, server_default=sa.text('false'), nullable=False),
        sa.Column('dispatched_at', sa.DateTime(timezone=True), nullable=True),
    )

def downgrade():
    op.drop_table('execution_outbox')
