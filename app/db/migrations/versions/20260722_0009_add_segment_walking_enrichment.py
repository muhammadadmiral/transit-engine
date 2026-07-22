"""Add walking enrichment columns to segments.

Revision ID: 20260722_0009
Revises: 20260721_0008
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0009"
down_revision: str | None = "20260721_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("segments", sa.Column("walking_distance_meters", sa.Float(), nullable=True))
    op.add_column(
        "segments", sa.Column("walking_route_source", sa.String(length=16), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("segments", "walking_route_source")
    op.drop_column("segments", "walking_distance_meters")
