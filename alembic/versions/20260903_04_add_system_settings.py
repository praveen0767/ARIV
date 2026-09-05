'''Revision ID: add_system_settings
Revises: add_execution_outbox_table
Create Date: 2026-09-03 23:40:00.000000

Creates a generic key/value store for system-level configuration.
Seeds execution_enabled = false (fail-closed by default).
'''

from alembic import op
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg

# revision identifiers, used by Alembic.
revision = 'add_system_settings'
down_revision = 'add_execution_outbox_table'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'system_settings',
        sa.Column(
            'id',
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text('gen_random_uuid()'),
            nullable=False,
        ),
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('value', sa.JSON, nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.UniqueConstraint('key', name='uq_system_settings_key'),
    )

    # Seed: execution is disabled by default (fail-closed).
    # The value is stored as JSON boolean false so it is unambiguous.
    op.execute(
        sa.text(
            "INSERT INTO system_settings (key, value) "
            "VALUES ('execution_enabled', 'false'::jsonb)"
        )
    )


def downgrade():
    op.drop_table('system_settings')
