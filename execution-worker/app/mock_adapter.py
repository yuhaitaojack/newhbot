from __future__ import annotations

import time
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from app.protocol import (
    BalanceView,
    FillView,
    OrderSide,
    OrderStatus,
    OrderView,
    PlaceOrderRequest,
    PlaceOrderResponse,
    PositionSide,
    PositionView,
)


class PlaceBehavior(StrEnum):
    FILL = "fill"
    PARTIAL = "partial"
    REJECT = "reject"
    OPEN = "open"
    TIMEOUT_AFTER_ACCEPT = "timeout_after_accept"
    NETWORK_BEFORE_ACCEPT = "network_before_accept"


class MockExecutionAdapter:
    """In-memory mock exchange. Never talks to Hyperliquid."""

    def __init__(self) -> None:
        self.connected = False
        self.equity = Decimal("10000")
        self.available = Decimal("10000")
        self.margin_used = Decimal("0")
        self.mid = Decimal("100")
        self.leverage: dict[str, int] = {}
        self.positions: dict[str, PositionView] = {}
        self.orders: dict[str, OrderView] = {}
        self.fills: list[FillView] = []
        self.behavior = PlaceBehavior.FILL
        self.query_fail = False
        self._oid = 1

    def set_behavior(self, behavior: str) -> None:
        self.behavior = PlaceBehavior(behavior)

    def set_query_fail(self, enabled: bool) -> None:
        self.query_fail = enabled

    def _raise_if_query_fail(self) -> None:
        if self.query_fail:
            raise TimeoutError("mock query fail")

    def force_position(self, symbol: str, side: PositionSide, size: Decimal, entry: Decimal | None = None) -> None:
        self.positions[symbol] = PositionView(
            symbol=symbol,
            side=side,
            size=size,
            entry_price=entry or self.mid,
            unrealized_pnl=Decimal("0"),
        )

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def get_balance(self) -> BalanceView:
        return BalanceView(equity=self.equity, available=self.available, margin_used=self.margin_used)

    async def get_available_balance(self) -> Decimal:
        return self.available

    async def get_positions(self) -> list[PositionView]:
        return [item for item in self.positions.values() if item.side != PositionSide.FLAT]

    async def get_position(self, symbol: str) -> PositionView:
        return self.positions.get(
            symbol,
            PositionView(symbol=symbol, side=PositionSide.FLAT, size=Decimal("0")),
        )

    async def get_open_orders(self, symbol: str | None = None) -> list[OrderView]:
        rows = [item for item in self.orders.values() if item.status in {OrderStatus.OPEN, OrderStatus.PARTIAL}]
        if symbol:
            rows = [item for item in rows if item.symbol == symbol]
        return rows

    async def get_order(self, cloid: str) -> OrderView | None:
        self._raise_if_query_fail()
        return self.orders.get(cloid)

    async def get_fills(self) -> list[FillView]:
        self._raise_if_query_fail()
        return list(self.fills)

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        self.leverage[symbol] = leverage

    async def get_market_data(self, symbol: str) -> dict[str, Decimal]:
        _ = symbol
        return {"mid": self.mid, "bid": self.mid - Decimal("0.1"), "ask": self.mid + Decimal("0.1")}

    async def get_candles(self, symbol: str, interval: str, limit: int = 200) -> list[dict]:
        _ = symbol
        step_by_unit = {
            "s": 1_000,
            "m": 60_000,
            "h": 3_600_000,
            "d": 86_400_000,
            "M": 2_592_000_000,
        }
        if not interval or interval[-1] not in step_by_unit:
            raise ValueError("unsupported candle interval")
        try:
            step_ms = int(interval[:-1]) * step_by_unit[interval[-1]]
        except (TypeError, ValueError):
            raise ValueError("unsupported candle interval") from None
        if step_ms <= 0:
            raise ValueError("unsupported candle interval")

        count = max(0, int(limit))
        if count == 0:
            return []
        now_ms = int(time.time() * 1_000)
        last_timestamp = now_ms - (now_ms % step_ms)
        price = self.mid
        return [
            {
                "timestamp": last_timestamp - step_ms * (count - index - 1),
                "open": str(price),
                "high": str(price),
                "low": str(price),
                "close": str(price),
                "volume": "0",
            }
            for index in range(count)
        ]

    async def place_order(self, request: PlaceOrderRequest) -> PlaceOrderResponse:
        if not self.connected:
            raise RuntimeError("mock exchange is not connected")
        if self.behavior == PlaceBehavior.NETWORK_BEFORE_ACCEPT:
            raise TimeoutError("mock network error before accept")
        if request.cloid in self.orders:
            existing = self.orders[request.cloid]
            return PlaceOrderResponse(
                request_id=request.request_id,
                cloid=request.cloid,
                exchange_oid=existing.exchange_oid,
                status=existing.status,
                filled_quantity=existing.filled_quantity,
                avg_price=existing.price,
                error="duplicate cloid ignored",
            )

        oid = str(self._oid)
        self._oid += 1
        order = OrderView(
            cloid=request.cloid,
            exchange_oid=oid,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            filled_quantity=Decimal("0"),
            reduce_only=request.reduce_only,
            status=OrderStatus.OPEN,
            price=request.price or self.mid,
        )
        self.orders[request.cloid] = order

        if self.behavior == PlaceBehavior.TIMEOUT_AFTER_ACCEPT:
            raise TimeoutError("mock timeout after exchange accepted order")
        if self.behavior == PlaceBehavior.REJECT:
            order.status = OrderStatus.REJECTED
            return PlaceOrderResponse(
                request_id=request.request_id,
                cloid=request.cloid,
                exchange_oid=oid,
                status=OrderStatus.REJECTED,
                error="mock reject",
            )
        if self.behavior == PlaceBehavior.OPEN:
            return PlaceOrderResponse(
                request_id=request.request_id,
                cloid=request.cloid,
                exchange_oid=oid,
                status=OrderStatus.OPEN,
            )

        fill_qty = request.quantity
        status = OrderStatus.FILLED
        if self.behavior == PlaceBehavior.PARTIAL:
            fill_qty = request.quantity / Decimal("2")
            status = OrderStatus.PARTIAL
            order.status = OrderStatus.PARTIAL
            order.filled_quantity = fill_qty
        else:
            order.status = OrderStatus.FILLED
            order.filled_quantity = fill_qty

        self.fills.append(
            FillView(
                cloid=request.cloid,
                symbol=request.symbol,
                side=request.side,
                price=self.mid,
                quantity=fill_qty,
            )
        )
        self._apply_fill(request, fill_qty)
        return PlaceOrderResponse(
            request_id=request.request_id,
            cloid=request.cloid,
            exchange_oid=oid,
            status=status,
            filled_quantity=fill_qty,
            avg_price=self.mid,
        )

    async def open_long(self, request: PlaceOrderRequest) -> PlaceOrderResponse:
        payload = request.model_copy(update={"side": OrderSide.BUY, "reduce_only": False, "command": "open_long"})
        return await self.place_order(payload)

    async def open_short(self, request: PlaceOrderRequest) -> PlaceOrderResponse:
        payload = request.model_copy(update={"side": OrderSide.SELL, "reduce_only": False, "command": "open_short"})
        return await self.place_order(payload)

    async def close_position(self, request: PlaceOrderRequest) -> PlaceOrderResponse:
        payload = request.model_copy(update={"reduce_only": True, "command": "close_position"})
        return await self.place_order(payload)

    async def stream_events(self):
        yield {"type": "hello", "mode": "mock", "connected": self.connected}

    async def cancel_order(self, cloid: str, request_id: str) -> OrderView | None:
        _ = request_id
        order = self.orders.get(cloid)
        if order is None:
            return None
        if order.status in {OrderStatus.OPEN, OrderStatus.PARTIAL}:
            order.status = OrderStatus.CANCELED
        return order

    def _apply_fill(self, request: PlaceOrderRequest, fill_qty: Decimal) -> None:
        current = self.positions.get(
            request.symbol,
            PositionView(symbol=request.symbol, side=PositionSide.FLAT, size=Decimal("0")),
        )
        if request.reduce_only:
            if current.side == PositionSide.FLAT:
                return
            remaining = current.size - fill_qty
            if remaining <= 0:
                self.positions[request.symbol] = PositionView(
                    symbol=request.symbol, side=PositionSide.FLAT, size=Decimal("0")
                )
            else:
                current.size = remaining
                self.positions[request.symbol] = current
            return
        if request.side == OrderSide.BUY:
            self.positions[request.symbol] = PositionView(
                symbol=request.symbol,
                side=PositionSide.LONG,
                size=current.size + fill_qty if current.side == PositionSide.LONG else fill_qty,
                entry_price=self.mid,
            )
        else:
            self.positions[request.symbol] = PositionView(
                symbol=request.symbol,
                side=PositionSide.SHORT,
                size=current.size + fill_qty if current.side == PositionSide.SHORT else fill_qty,
                entry_price=self.mid,
            )


def new_request_id() -> str:
    return str(uuid4())
