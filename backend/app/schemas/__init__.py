from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.core.enums import OrderSide, OrderStatus, OrderType, PositionSide, SignalType, SystemState


class SettingsOut(BaseModel):
    trading_pair: str
    leverage: int
    position_percentage: Decimal
    order_type: str
    limit_timeout: int
    slippage: Decimal
    active_strategy: str | None
    active_strategy_version: str | None
    trading_enabled: bool
    estop: bool
    close_intent: str | None
    system_state: str


class SettingsUpdate(BaseModel):
    trading_pair: str | None = None
    leverage: int | None = Field(default=None, ge=1, le=100)
    position_percentage: Decimal | None = None
    order_type: str | None = None
    limit_timeout: int | None = None
    slippage: Decimal | None = None
    active_strategy: str | None = None
    active_strategy_version: str | None = None
    estop: bool | None = None


class StrategyParameterOut(BaseModel):
    id: int
    name: str
    type: str
    default_value: str
    current_value: str
    enabled: bool
    min_value: str | None
    max_value: str | None
    description: str | None
    effective_value: str


class StrategyVersionOut(BaseModel):
    id: int
    name: str
    version: str
    file_hash: str
    path: str
    created_at: datetime


class StrategyOut(BaseModel):
    active_strategy: str | None
    active_strategy_version: str | None
    versions: list[StrategyVersionOut]
    parameters: list[StrategyParameterOut]


class PositionOut(BaseModel):
    symbol: str
    side: PositionSide
    size: Decimal
    entry_price: Decimal | None
    unrealized_pnl: Decimal
    source: str = "local_mirror"
    note: str = "Exchange State > Local DB. This is a mirror/audit row only."


class OrderOut(BaseModel):
    id: str
    intent_id: str
    request_id: str
    cloid: str
    exchange_oid: str | None
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    reduce_only: bool
    status: OrderStatus
    signal_id: str | None
    error_message: str | None
    created_at: datetime


class FillOut(BaseModel):
    id: str
    order_id: str
    cloid: str
    symbol: str
    side: OrderSide
    price: Decimal
    quantity: Decimal
    fee: Decimal
    created_at: datetime


class TradeOut(BaseModel):
    id: str
    symbol: str
    side: str
    entry_price: Decimal
    exit_price: Decimal | None
    quantity: Decimal
    pnl: Decimal | None
    opened_at: datetime
    closed_at: datetime | None


class EventOut(BaseModel):
    id: int
    event_type: str
    payload_json: str
    created_at: datetime


class HealthOut(BaseModel):
    status: str
    execution_mode: str
    worker_ok: bool
    worker_ready: bool = False
    worker_state: str | None = None
    execution_enabled: bool = False
    sync_status: str | None = None


class StatusOut(BaseModel):
    system_state: SystemState
    trading_enabled: bool
    estop: bool
    last_signal: SignalType | None
    last_signal_reason: str | None
    settings: SettingsOut
    position: PositionOut
    last_order: OrderOut | None
    last_fill: FillOut | None
    balance: dict[str, Decimal]
    snapshot_event_id: int
    worker_ready: bool = False
    worker_state: str | None = None
    sync_status: str | None = None
