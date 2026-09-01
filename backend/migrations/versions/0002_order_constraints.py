"""open reservation + unique order keys

Revision ID: 0002_order_constraints
Revises: 0001_initial
Create Date: 2026-09-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_order_constraints"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("uq_orders_intent_id", "orders", ["intent_id"], unique=True)
    op.create_index("uq_orders_request_id", "orders", ["request_id"], unique=True)
    op.execute(
        """
        CREATE UNIQUE INDEX uq_orders_inflight_open_per_symbol
        ON orders(symbol)
        WHERE reduce_only = 0 AND status IN
            ('PENDING_SUBMISSION','SUBMITTING','ACK','OPEN','PARTIAL','UNKNOWN')
        """
    )
    op.create_table(
        "open_reservations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.String(length=36), nullable=True, unique=True),
        sa.Column("held_reason", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.execute("INSERT INTO open_reservations (id, order_id, held_reason) VALUES (1, NULL, NULL)")


def downgrade() -> None:
    op.drop_table("open_reservations")
    op.execute("DROP INDEX IF EXISTS uq_orders_inflight_open_per_symbol")
    op.drop_index("uq_orders_request_id", table_name="orders")
    op.drop_index("uq_orders_intent_id", table_name="orders")
