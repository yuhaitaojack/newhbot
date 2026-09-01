from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field


class PositionSide(StrEnum):
    FLAT = "FLAT"
    LONG = "LONG"
    SHORT = "SHORT"
    UNKNOWN = "UNKNOWN"


class OrderStatus(StrEnum):
    PENDING_SUBMISSION = "PENDING_SUBMISSION"
    UNKNOWN = "UNKNOWN"
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELED = "CANCELED"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class PlaceOrderRequest(BaseModel):
    request_id: str
    cloid: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    command: str = "place_order"
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    reduce_only: bool = False
    price: Decimal | None = None


class PlaceOrderResponse(BaseModel):
    request_id: str
    cloid: str
    exchange_oid: str | None = None
    status: OrderStatus
    filled_quantity: Decimal = Decimal("0")
    avg_price: Decimal | None = None
    error: str | None = None


class OrderView(BaseModel):
    cloid: str
    exchange_oid: str | None = None
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    filled_quantity: Decimal = Decimal("0")
    reduce_only: bool = False
    status: OrderStatus
    price: Decimal | None = None


class PositionView(BaseModel):
    symbol: str
    side: PositionSide
    size: Decimal
    entry_price: Decimal | None = None
    unrealized_pnl: Decimal = Decimal("0")


class BalanceView(BaseModel):
    equity: Decimal
    available: Decimal
    margin_used: Decimal = Decimal("0")


class FillView(BaseModel):
    cloid: str
    symbol: str
    side: OrderSide
    price: Decimal
    quantity: Decimal
    fee: Decimal = Decimal("0")


class ExecutionAdapter(Protocol):
    """Exchange adapter. Business strategy must never call this directly.

    TradingController talks to the worker over RPC (`place_order`, not these helpers).
    `open_long` / `open_short` / `close_position` exist so a future Hyperliquid
    adapter can keep the same surface as Mock without leaking connector objects.
    """

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def get_balance(self) -> BalanceView: ...
    async def get_available_balance(self) -> Decimal: ...
    async def get_positions(self) -> list[PositionView]: ...
    async def get_position(self, symbol: str) -> PositionView: ...
    async def get_open_orders(self, symbol: str | None = None) -> list[OrderView]: ...
    async def get_order(self, cloid: str) -> OrderView | None: ...
    async def get_fills(self) -> list[FillView]: ...
    async def set_leverage(self, symbol: str, leverage: int) -> None: ...
    async def place_order(self, request: PlaceOrderRequest) -> PlaceOrderResponse: ...
    async def open_long(self, request: PlaceOrderRequest) -> PlaceOrderResponse: ...
    async def open_short(self, request: PlaceOrderRequest) -> PlaceOrderResponse: ...
    async def close_position(self, request: PlaceOrderRequest) -> PlaceOrderResponse: ...
    async def cancel_order(self, cloid: str, request_id: str) -> OrderView | None: ...
    async def get_market_data(self, symbol: str) -> dict[str, Decimal]: ...
    async def stream_events(self) -> AsyncIterator[dict]: ...
