"""
SystemSetting — generic key/value store for system-level configuration.

This model deliberately avoids column-per-setting design so that new
operational knobs (rate limits, feature flags, provider toggles) can be
added without schema migrations. The JSON value column is the authoritative
source of truth; callers are responsible for interpreting the type.

CURRENT SETTINGS
----------------
key                 | type      | default | meaning
--------------------+-----------+---------+-----------------------------
execution_enabled   | bool      | false   | Global execution kill switch.
                    |           |         | Must be explicitly set to
                    |           |         | true before any provider
                    |           |         | mutation is allowed.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects.postgresql import JSONB

from app.domain.base import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    key = Column(String(255), nullable=False, unique=True)
    # JSON value — intentionally untyped at the ORM level.
    # Callers must validate the Python type they receive.
    value = Column(JSONB, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SystemSetting key={self.key!r} value={self.value!r}>"
