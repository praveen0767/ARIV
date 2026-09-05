"""add_system_setting_entry

Revision ID: 8c7cccd2f6ba
Revises: 24f14e1d95bb
Create Date: 2026-09-03 19:07:14.944388

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8c7cccd2f6ba'
down_revision: Union[str, Sequence[str], None] = '24f14e1d95bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "INSERT INTO system_settings (key, value) VALUES ('recovery_attribution_window_seconds', '86400') ON CONFLICT (key) DO NOTHING"
    )

def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "DELETE FROM system_settings WHERE key = 'recovery_attribution_window_seconds'"
    )
