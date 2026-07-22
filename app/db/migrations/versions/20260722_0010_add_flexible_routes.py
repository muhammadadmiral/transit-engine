"""Store hail-and-ride services as corridors rather than fixed stops.

Revision ID: 20260722_0010
Revises: 20260722_0009
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry

revision: str = "20260722_0010"
down_revision: str | None = "20260722_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "flexible_routes",
        sa.Column("id", sa.String(length=120), primary_key=True),
        sa.Column("route_code", sa.String(length=80), nullable=False),
        sa.Column("route_name", sa.String(length=255), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("service_category", sa.String(length=32), nullable=False),
        sa.Column("service_name", sa.String(length=255), nullable=False),
        sa.Column("avg_speed_kmh", sa.Float(), nullable=False),
        sa.Column("fare", sa.Integer(), nullable=False),
        sa.Column("fare_product_id", sa.String(length=120), nullable=False),
        sa.Column("data_confidence", sa.String(length=16), nullable=False),
        sa.Column("last_verified_at", sa.Date(), nullable=False),
        sa.Column("color", sa.String(length=6), nullable=False),
        sa.Column("geometry", Geometry("LINESTRING", srid=4326), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
    )
    op.create_index("ix_flexible_routes_route_code", "flexible_routes", ["route_code"])
    op.create_index("ix_flexible_routes_mode", "flexible_routes", ["mode"])
    op.create_index("ix_flexible_routes_fare_product_id", "flexible_routes", ["fare_product_id"])


def downgrade() -> None:
    op.drop_table("flexible_routes")
