from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SettingsRow(Base):
    """Persisted trading settings. Survives process and container restart."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_pair: Mapped[str] = mapped_column(String(64), nullable=False, default="BTC-USD")
    leverage: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    position_percentage: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=Decimal("10"))
    order_type: Mapped[str] = mapped_column(String(16), nullable=False, default="MARKET")
    limit_timeout: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    slippage: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=Decimal("0.05"))
    active_strategy: Mapped[str | None] = mapped_column(String(128), nullable=True)
    active_strategy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trading_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    estop: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    close_intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    system_state: Mapped[str] = mapped_column(String(32), nullable=False, default="STOPPED")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StrategyVersion(Base):
    __tablename__ = "strategy_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StrategyParameter(Base):
    __tablename__ = "strategy_parameters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_version_id: Mapped[int] = mapped_column(ForeignKey("strategy_versions.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    default_value: Mapped[str] = mapped_column(Text, nullable=False)
    current_value: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    min_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    strategy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signal: Mapped[str] = mapped_column(String(16), nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    intent_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    cloid: Mapped[str] = mapped_column(String(66), nullable=False, unique=True, index=True)
    exchange_oid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)
    reduce_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    signal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Fill(Base):
    __tablename__ = "fills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    cloid: Mapped[str] = mapped_column(String(66), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 12), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)
    pnl: Mapped[Decimal | None] = mapped_column(Numeric(28, 12), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Position(Base):
    """Local position MIRROR / audit only.

    Exchange State > Local DB. Never treat this row as live truth.
    """

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    side: Mapped[str] = mapped_column(String(16), nullable=False, default="FLAT")
    size: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False, default=Decimal("0"))
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 12), nullable=True)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False, default=Decimal("0"))
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="local_mirror")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equity: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)
    available: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)
    margin_used: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SystemEvent(Base):
    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
