"""Add auditable scheduled service-frequency windows.

Revision ID: 20260722_0011
Revises: 20260722_0010
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0011"
down_revision: str | None = "20260722_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_frequencies",
        sa.Column("id", sa.String(length=160), primary_key=True),
        sa.Column("route_id", sa.String(length=120), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("day_type", sa.String(length=16), nullable=False),
        sa.Column("start_minute", sa.Integer(), nullable=False),
        sa.Column("end_minute", sa.Integer(), nullable=False),
        sa.Column("headway_min", sa.Float(), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=False),
        sa.Column("last_verified_at", sa.Date(), nullable=False),
        sa.CheckConstraint("start_minute >= 0 AND start_minute < 1440"),
        sa.CheckConstraint("end_minute > start_minute AND end_minute <= 1440"),
        sa.CheckConstraint("headway_min > 0"),
    )
    op.create_index("ix_service_frequencies_route_id", "service_frequencies", ["route_id"])
    op.create_index("ix_service_frequencies_mode", "service_frequencies", ["mode"])


def downgrade() -> None:
    op.drop_table("service_frequencies")
