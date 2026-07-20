"""Add normalized and operator-native service classification to segments.

Revision ID: 20260720_0003
Revises: 20260720_0002
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260720_0003"
down_revision: str | None = "20260720_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "segments",
        sa.Column("service_category", sa.String(length=32), server_default="main", nullable=False),
    )
    op.add_column(
        "segments",
        sa.Column("service_name", sa.String(length=64), server_default="Unknown", nullable=False),
    )
    op.alter_column("segments", "service_category", server_default=None)
    op.alter_column("segments", "service_name", server_default=None)


def downgrade() -> None:
    op.drop_column("segments", "service_name")
    op.drop_column("segments", "service_category")
