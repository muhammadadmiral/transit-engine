"""Add an expression index for meter-based nearby-stop queries.

Revision ID: 20260720_0007
Revises: 20260720_0006
Create Date: 2026-07-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260720_0007"
down_revision: str | None = "20260720_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_stops_location_geography " "ON stops USING gist ((location::geography))"
    )


def downgrade() -> None:
    op.drop_index("ix_stops_location_geography", table_name="stops")
