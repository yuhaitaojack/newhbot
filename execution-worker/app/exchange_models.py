from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field

from app.protocol import OrderSide, OrderStatus, OrderType, PositionSide


class WorkerState(StrEnum):
    NOT_READY = "NOT_READY"
    RECOVERING = "RECOVERING"
    READY = "READY"
    DEGRADED = "DEGRADED"


class SyncStatus(StrEnum):
    NONE = "NONE"
    SNAPSHOT = "SNAPSHOT"
    LIVE = "LIVE"
    RESYNC = "RESYNC"
    CONFLICT = "CONFLICT"


class ExchangePosition(BaseModel):
    symbol: str
    side: PositionSide
    size: Decimal
    entry_price: Decimal | None = None
    mark_price: Decimal | None = None
    unrealized_pnl: Decimal = Decimal("0")
    leverage: int | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExchangeOrder(BaseModel):
    exchange_order_id: str | None = None
    cloid: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    price: Decimal | None = None
    quantity: Decimal
    filled_quantity: Decimal = Decimal("0")
    remaining_quantity: Decimal = Decimal("0")
    reduce_only: bool = False
    status: OrderStatus
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExchangeFill(BaseModel):
    fill_id: str
    order_id: str | None = None
    cloid: str
    symbol: str
    side: OrderSide
    price: Decimal
    quantity: Decimal
    fee: Decimal = Decimal("0")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExchangeAccount(BaseModel):
    equity: Decimal
    available: Decimal
    margin_used: Decimal = Decimal("0")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExchangeEvent(BaseModel):
    event_type: str
    payload: dict
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InstrumentMeta(BaseModel):
    symbol: str
    sz_decimals: int
    step_size: Decimal
    tick_size: Decimal
    min_order_size: Decimal
    min_notional: Decimal
    max_leverage: int | None = None
