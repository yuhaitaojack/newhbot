"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trading_pair", sa.String(length=64), nullable=False),
        sa.Column("leverage", sa.Integer(), nullable=False),
        sa.Column("position_percentage", sa.Numeric(18, 8), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("limit_timeout", sa.Integer(), nullable=False),
        sa.Column("slippage", sa.Numeric(18, 8), nullable=False),
        sa.Column("active_strategy", sa.String(length=128), nullable=True),
        sa.Column("active_strategy_version", sa.String(length=64), nullable=True),
        sa.Column("trading_enabled", sa.Boolean(), nullable=False),
        sa.Column("estop", sa.Boolean(), nullable=False),
        sa.Column("close_intent", sa.String(length=32), nullable=True),
        sa.Column("system_state", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "strategy_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "strategy_parameters",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("strategy_version_id", sa.Integer(), sa.ForeignKey("strategy_versions.id"), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("default_value", sa.Text(), nullable=False),
        sa.Column("current_value", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("min_value", sa.Text(), nullable=True),
        sa.Column("max_value", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_table(
        "signals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("strategy_version", sa.String(length=64), nullable=True),
        sa.Column("signal", sa.String(length=16), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("intent_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("cloid", sa.String(length=66), nullable=False),
        sa.Column("exchange_oid", sa.String(length=64), nullable=True),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 12), nullable=False),
        sa.Column("reduce_only", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("signal_id", sa.String(length=36), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_orders_cloid", "orders", ["cloid"], unique=True)
    op.create_table(
        "fills",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("order_id", sa.String(length=36), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("cloid", sa.String(length=66), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("price", sa.Numeric(28, 12), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 12), nullable=False),
        sa.Column("fee", sa.Numeric(28, 12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "trades",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("entry_price", sa.Numeric(28, 12), nullable=False),
        sa.Column("exit_price", sa.Numeric(28, 12), nullable=True),
        sa.Column("quantity", sa.Numeric(28, 12), nullable=False),
        sa.Column("pnl", sa.Numeric(28, 12), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("size", sa.Numeric(28, 12), nullable=False),
        sa.Column("entry_price", sa.Numeric(28, 12), nullable=True),
        sa.Column("unrealized_pnl", sa.Numeric(28, 12), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_positions_symbol", "positions", ["symbol"], unique=True)
    op.create_table(
        "account_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("equity", sa.Numeric(28, 12), nullable=False),
        sa.Column("available", sa.Numeric(28, 12), nullable=False),
        sa.Column("margin_used", sa.Numeric(28, 12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "system_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    for table in [
        "audit_logs",
        "system_events",
        "account_snapshots",
        "positions",
        "trades",
        "fills",
        "orders",
        "signals",
        "strategy_parameters",
        "strategy_versions",
        "settings",
    ]:
        op.drop_table(table)
