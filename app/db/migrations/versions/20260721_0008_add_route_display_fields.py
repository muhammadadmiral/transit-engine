"""add route display fields

Revision ID: 20260721_0008
Revises: 20260720_0007
Create Date: 2026-07-21
"""

import sqlalchemy as sa
from alembic import op

revision = "20260721_0008"
down_revision = "20260720_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("segments", sa.Column("route_code", sa.String(length=80), nullable=True))
    op.add_column("segments", sa.Column("route_name", sa.String(length=255), nullable=True))
    op.execute(
        """
        UPDATE segments
        SET route_code = CASE
            WHEN mode = 'transjakarta' THEN split_part(route_id, ':', 2)
            WHEN mode = 'angkot' THEN upper(split_part(route_id, ':', 4))
            WHEN mode = 'walk' THEN 'WALK'
            ELSE upper(replace(split_part(route_id, ':', 2), '-', ' '))
        END,
        route_name = service_name
        """
    )
    op.alter_column("segments", "route_code", nullable=False)
    op.alter_column("segments", "route_name", nullable=False)
    op.create_index("ix_segments_route_code", "segments", ["route_code"])


def downgrade() -> None:
    op.drop_index("ix_segments_route_code", table_name="segments")
    op.drop_column("segments", "route_name")
    op.drop_column("segments", "route_code")
