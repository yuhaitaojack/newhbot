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
        self.health_error = False
        self.ready_error = False
        self.equity = Decimal("10000")
        self.available = Decimal("10000")
        self.mid = Decimal("100")
        self.candles: list[dict] = []
        self.positions: dict[str, PositionView] = {}
        self.orders: dict[str, OrderView] = {}
        self.fills: list[FillView] = []
        self.place_mode = "fill"
        self.place_calls = 0
        self.cancel_calls = 0
        self.cancel_order_error = False
        self.set_leverage_calls = 0
        self.place_delay = 0.0
        self.get_order_error = False
        self.get_fills_error = False
        self.get_position_error = False
        self.get_candles_error = False
        self.get_balance_error = False
        self.worker_status_error = False
        self.inject_fill_on_network_fail = False
        self.sync_error_after_timeout = False
        self._oid = 1

    async def health(self) -> bool:
        if self.health_error:
            raise TimeoutError("fake health failed")
        return self.healthy

    async def is_ready(self) -> bool:
        if self.ready_error:
            raise TimeoutError("fake is_ready failed")
        return self.healthy and self.ready_flag

    async def worker_status(self) -> dict:
        if self.worker_status_error:
            raise TimeoutError("fake worker_status failed")
        ready = self.healthy and self.ready_flag
        return {
            "ready": ready,
            "worker_state": "READY" if ready else "NOT_READY",
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
        if self.get_balance_error:
            raise TimeoutError("fake get_balance failed")
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
        self.set_leverage_calls += 1
        _ = (symbol, leverage)

    async def get_market_data(self, symbol: str) -> dict[str, Decimal]:
        _ = symbol
        return {"mid": self.mid}

    async def get_candles(self, symbol: str, interval: str, limit: int = 200) -> list[dict]:
        if self.get_candles_error:
            raise TimeoutError("fake get_candles failed")
        _ = (symbol, interval, limit)
        return list(self.candles)

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
            if self.sync_error_after_timeout:
                self.get_balance_error = True
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
        # In the IOC acknowledgement mode the connector response is OPEN,
        # while the exchange-side order is already complete.
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
        response_status = (
            OrderStatus.OPEN
            if self.place_mode == "open_but_filled_position"
            else order.status
        )
        response_filled = (
            Decimal("0")
            if self.place_mode == "open_but_filled_position"
            else fill_qty
        )
        return PlaceOrderResponse(
            request_id=request.request_id,
            cloid=request.cloid,
            exchange_oid=oid,
            status=response_status,
            filled_quantity=response_filled,
            avg_price=self.mid if response_filled > 0 else None,
        )

    async def stream_events(self):
        yield {"type": "hello", "mode": "fake"}

    async def cancel_order(self, cloid: str, request_id: str) -> OrderView | None:
        self.cancel_calls += 1
        _ = request_id
        if self.cancel_order_error:
            raise TimeoutError("fake cancel_order failed")
        order = self.orders.get(cloid)
        if order and order.status in {OrderStatus.OPEN, OrderStatus.PARTIAL}:
            order.status = OrderStatus.CANCELED
        return order
