"""Associate transit segments with a whole-journey fare product.

Revision ID: 20260720_0004
Revises: 20260720_0003
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260720_0004"
down_revision: str | None = "20260720_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "segments",
        sa.Column("fare_product_id", sa.String(length=120), nullable=True),
    )
    op.execute(
        "UPDATE segments SET fare_product_id = 'transjakarta:regular' "
        "WHERE mode = 'transjakarta'"
    )
    op.execute(
        "UPDATE segments SET fare_product_id = 'legacy:' || mode "
        "WHERE fare_product_id IS NULL"
    )
    op.alter_column("segments", "fare_product_id", nullable=False)
    op.create_index("ix_segments_fare_product_id", "segments", ["fare_product_id"])


def downgrade() -> None:
    op.drop_index("ix_segments_fare_product_id", table_name="segments")
    op.drop_column("segments", "fare_product_id")
