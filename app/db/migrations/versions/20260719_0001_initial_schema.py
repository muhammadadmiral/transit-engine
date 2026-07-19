"""initial transit persistence schema

Revision ID: 20260719_0001
Revises:
Create Date: 2026-07-19
"""

from alembic import op
from geoalchemy2 import Geometry
import sqlalchemy as sa


revision = "20260719_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.create_table(
        "stops",
        sa.Column("id", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("location", Geometry("POINT", srid=4326), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "segments",
        sa.Column("id", sa.String(length=120), nullable=False),
        sa.Column("from_stop_id", sa.String(length=120), nullable=False),
        sa.Column("to_stop_id", sa.String(length=120), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("avg_duration_min", sa.Float(), nullable=False),
        sa.Column("fare", sa.Integer(), nullable=False),
        sa.Column("data_confidence", sa.String(length=16), nullable=False),
        sa.Column("last_verified_at", sa.Date(), nullable=False),
        sa.Column("color", sa.String(length=6), nullable=False),
        sa.Column("geometry", Geometry("LINESTRING", srid=4326), nullable=False),
        sa.ForeignKeyConstraint(["from_stop_id"], ["stops.id"]),
        sa.ForeignKeyConstraint(["to_stop_id"], ["stops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_segments_from_stop_id", "segments", ["from_stop_id"])
    op.create_index("ix_segments_to_stop_id", "segments", ["to_stop_id"])


def downgrade() -> None:
    op.drop_index("ix_segments_to_stop_id", table_name="segments")
    op.drop_index("ix_segments_from_stop_id", table_name="segments")
    op.drop_table("segments")
    op.drop_table("stops")
