from __future__ import annotations

import asyncio
from decimal import Decimal

from app.core.enums import OrderStatus, PositionSide
from app.execution.protocol import (
    BalanceView,
    FillView,
    OrderView,
    PlaceOrderRequest,
    PlaceOrderResponse,
    PositionView,
)


class FakeExecutionClient:
    """In-process double for tests. Not used by API routes directly."""

    def __init__(self) -> None:
        self.connected = False
        self.healthy = True
        self.ready_flag = True
        self.equity = Decimal("10000")
        self.available = Decimal("10000")
        self.mid = Decimal("100")
        self.positions: dict[str, PositionView] = {}
        self.orders: dict[str, OrderView] = {}
        self.fills: list[FillView] = []
        self.place_mode = "fill"
        self.place_calls = 0
        self.place_delay = 0.0
        self.get_order_error = False
        self.get_fills_error = False
        self.get_position_error = False
        self.inject_fill_on_network_fail = False
        self._oid = 1

    async def health(self) -> bool:
        return self.healthy

    async def is_ready(self) -> bool:
        return self.healthy and self.ready_flag

    async def worker_status(self) -> dict:
        return {
            "ready": self.healthy,
            "worker_state": "READY" if self.healthy else "NOT_READY",
            "mode": "fake",
            "execution_enabled": False,
        }

    async def configure(self, trading_pair: str, slippage, leverage: int) -> None:
        _ = (trading_pair, slippage, leverage)

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def get_balance(self) -> BalanceView:
        return BalanceView(equity=self.equity, available=self.available, margin_used=Decimal("0"))

    async def get_positions(self) -> list[PositionView]:
        return [item for item in self.positions.values() if item.side != PositionSide.FLAT]

    async def get_position(self, symbol: str) -> PositionView:
        if self.get_position_error:
            raise TimeoutError("fake get_position failed")
        return self.positions.get(
            symbol, PositionView(symbol=symbol, side=PositionSide.FLAT, size=Decimal("0"))
        )

    async def get_open_orders(self, symbol: str | None = None) -> list[OrderView]:
        rows = list(self.orders.values())
        if symbol:
            rows = [item for item in rows if item.symbol == symbol]
        return [item for item in rows if item.status in {OrderStatus.OPEN, OrderStatus.PARTIAL}]

    async def get_order(self, cloid: str) -> OrderView | None:
        if self.get_order_error:
            raise TimeoutError("fake get_order failed")
        return self.orders.get(cloid)

    async def get_fills(self) -> list[FillView]:
        if self.get_fills_error:
            raise TimeoutError("fake get_fills failed")
        return list(self.fills)

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        _ = (symbol, leverage)

    async def get_market_data(self, symbol: str) -> dict[str, Decimal]:
        _ = symbol
        return {"mid": self.mid}

    async def place_order(self, request: PlaceOrderRequest) -> PlaceOrderResponse:
        self.place_calls += 1
        if self.place_delay:
            await asyncio.sleep(self.place_delay)
        if self.place_mode == "network_before_accept":
            if self.inject_fill_on_network_fail:
                self.fills.append(
                    FillView(
                        cloid=request.cloid,
                        symbol=request.symbol,
                        side=request.side,
                        price=self.mid,
                        quantity=request.quantity,
                    )
                )
            raise TimeoutError("fake network before accept")
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
            price=self.mid,
        )
        self.orders[request.cloid] = order
        if self.place_mode == "timeout_after_accept":
            raise TimeoutError("fake timeout after accept")
        if self.place_mode == "reject":
            order.status = OrderStatus.REJECTED
            return PlaceOrderResponse(
                request_id=request.request_id,
                cloid=request.cloid,
                exchange_oid=oid,
                status=OrderStatus.REJECTED,
                error="fake reject",
            )
        fill_qty = request.quantity / 2 if self.place_mode == "partial" else request.quantity
        order.status = OrderStatus.PARTIAL if self.place_mode == "partial" else OrderStatus.FILLED
        order.filled_quantity = fill_qty
        self.fills.append(
            FillView(cloid=request.cloid, symbol=request.symbol, side=request.side, price=self.mid, quantity=fill_qty)
        )
        current = await self.get_position(request.symbol)
        if request.reduce_only:
            remaining = current.size - fill_qty
            if remaining <= 0:
                self.positions[request.symbol] = PositionView(
                    symbol=request.symbol, side=PositionSide.FLAT, size=Decimal("0")
                )
            else:
                current.size = remaining
                self.positions[request.symbol] = current
        elif request.side.value == "BUY":
            self.positions[request.symbol] = PositionView(
                symbol=request.symbol, side=PositionSide.LONG, size=fill_qty, entry_price=self.mid
            )
        else:
            self.positions[request.symbol] = PositionView(
                symbol=request.symbol, side=PositionSide.SHORT, size=fill_qty, entry_price=self.mid
            )
        return PlaceOrderResponse(
            request_id=request.request_id,
            cloid=request.cloid,
            exchange_oid=oid,
            status=order.status,
            filled_quantity=fill_qty,
            avg_price=self.mid,
        )

    async def stream_events(self):
        yield {"type": "hello", "mode": "fake"}

    async def cancel_order(self, cloid: str, request_id: str) -> OrderView | None:
        _ = request_id
        order = self.orders.get(cloid)
        if order and order.status in {OrderStatus.OPEN, OrderStatus.PARTIAL}:
            order.status = OrderStatus.CANCELED
        return order
