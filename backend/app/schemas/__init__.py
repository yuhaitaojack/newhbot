from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

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
    trading_pair: str | None = Field(default=None, min_length=3, max_length=64, pattern=r"^[A-Za-z0-9]+-[A-Za-z0-9]+$")
    leverage: int | None = Field(default=None, ge=1, le=100)
    position_percentage: Decimal | None = Field(default=None, gt=0, le=100)
    order_type: Literal["MARKET", "LIMIT"] | None = None
    limit_timeout: int | None = Field(default=None, ge=1, le=86400)
    slippage: Decimal | None = Field(default=None, ge=0, lt=1)
    active_strategy: str | None = None
    active_strategy_version: str | None = None
    # estop cannot be changed here. Use POST /api/trading/clear-estop.


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


class StrategyParameterUpdate(BaseModel):
    enabled: bool | None = None
    current_value: str | None = Field(default=None, max_length=512)


class StrategyVersionOut(BaseModel):
    id: int
    name: str
    version: str
    file_hash: str
    path: str
    created_at: datetime


class StrategyActivateIn(BaseModel):
    file_hash: str = Field(min_length=64, max_length=64, pattern=r"^[a-fA-F0-9]{64}$")


class StrategyTickIn(BaseModel):
    snapshot: dict = Field(default_factory=dict)


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
    exchange_fill_id: str | None = None


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
    hyperliquid_domain: str | None = None


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
    hyperliquid_domain: str | None = None
    strategy_loop_running: bool = False
    strategy_loop_last_error: str | None = None
    strategy_loop_last_candle_timestamp: int | None = None
