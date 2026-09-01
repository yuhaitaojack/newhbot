from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, Field

from app.core.enums import OrderSide, OrderStatus, OrderType, PositionSide


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


class ExecutionClient(Protocol):
    """Narrow RPC to Execution Worker. Only TradingController may place/cancel."""

    async def health(self) -> bool: ...

    async def is_ready(self) -> bool: ...

    async def worker_status(self) -> dict: ...

    async def configure(self, trading_pair: str, slippage, leverage: int) -> None: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def get_balance(self) -> BalanceView: ...

    async def get_positions(self) -> list[PositionView]: ...

    async def get_position(self, symbol: str) -> PositionView: ...

    async def get_open_orders(self, symbol: str | None = None) -> list[OrderView]: ...

    async def get_order(self, cloid: str) -> OrderView | None: ...

    async def get_fills(self) -> list[FillView]: ...

    async def set_leverage(self, symbol: str, leverage: int) -> None: ...

    async def place_order(self, request: PlaceOrderRequest) -> PlaceOrderResponse: ...

    async def cancel_order(self, cloid: str, request_id: str) -> OrderView | None: ...

    async def get_market_data(self, symbol: str) -> dict[str, Decimal]: ...

    async def stream_events(self) -> AsyncIterator[dict]: ...
