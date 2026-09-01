"""fills.exchange_fill_id unique for WS reconnect idempotency

Revision ID: 0003_fill_idempotency
Revises: 0002_order_constraints
Create Date: 2026-09-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_fill_idempotency"
down_revision = "0002_order_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fills", sa.Column("exchange_fill_id", sa.String(length=128), nullable=True))
    op.create_index("uq_fills_exchange_fill_id", "fills", ["exchange_fill_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_fills_exchange_fill_id", table_name="fills")
    op.drop_column("fills", "exchange_fill_id")
