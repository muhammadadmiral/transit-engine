"""add route identity to segments

Revision ID: 20260720_0002
Revises: 20260719_0001
Create Date: 2026-07-20
"""

import sqlalchemy as sa
from alembic import op

revision = "20260720_0002"
down_revision = "20260719_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("segments", sa.Column("route_id", sa.String(length=120), nullable=True))
    op.execute("UPDATE segments SET route_id = id WHERE route_id IS NULL")
    op.alter_column("segments", "route_id", nullable=False)
    op.create_index("ix_segments_route_id", "segments", ["route_id"])


def downgrade() -> None:
    op.drop_index("ix_segments_route_id", table_name="segments")
    op.drop_column("segments", "route_id")
