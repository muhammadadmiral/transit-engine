"""Add mode indexes for filtered network map endpoints.

Revision ID: 20260720_0005
Revises: 20260720_0004
Create Date: 2026-07-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260720_0005"
down_revision: str | None = "20260720_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_stops_mode", "stops", ["mode"], unique=False)
    op.create_index("ix_segments_mode", "segments", ["mode"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_segments_mode", table_name="segments")
    op.drop_index("ix_stops_mode", table_name="stops")
