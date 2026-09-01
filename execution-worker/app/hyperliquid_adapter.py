from __future__ import annotations

from decimal import Decimal

from app.config import WorkerConfig
from app.connector_bridge import ConnectorBridge, FakeConnector
from app.exchange_models import InstrumentMeta, WorkerState
from app.ioc_price import ioc_limit_price
from app.instrument_meta import default_btc_instrument_meta
from app.mapping import OneWayError, map_clearinghouse_positions, map_hummingbot_fill, map_hummingbot_order
from app.reconciliation import compare_rest_and_hummingbot
from app.protocol import (
    BalanceView,
    FillView,
    OrderSide,
    OrderStatus,
    OrderType,
    OrderView,
    PlaceOrderRequest,
    PlaceOrderResponse,
    PositionSide,
    PositionView,
)
from app.quantization import QuantizeReject, normalize_order_request
from app.state_store import ExchangeStateStore


class ExecutionDisabled(RuntimeError):
    """Connector is wired but live place/cancel/leverage are forbidden."""


class HyperliquidExecutionAdapter:
    """Maps to Hummingbot Hyperliquid connector. Contains no strategy or Guard logic.

    Default: execution_enabled=False. Code present ≠ live trading.
    Never calls connector.buy()/sell() (those mint a new MD5 cloid in v2.16.0).
    Never retries place() for the same cloid.
    """

    def __init__(
        self,
        config: WorkerConfig,
        connector: ConnectorBridge | None = None,
        meta: InstrumentMeta | None = None,
    ) -> None:
        self.config = config
        self.connector = connector or FakeConnector()
        self.store = ExchangeStateStore()
        self.connected = False
        self.recovery_reason: str | None = None
        self.foreign_symbols: list[str] = []
        self.one_way_ok = True
        self.last_normalized: PlaceOrderRequest | None = None
        self.last_wire: dict | None = None
        self._submitted_cloids: set[str] = set()
        self.meta = meta or default_btc_instrument_meta()
        if self.meta.symbol != config.trading_pair:
            self.meta = self.meta.model_copy(update={"symbol": config.trading_pair})
        self.mid = Decimal("100")
        self.leverage_mismatch = False
        self.observed_leverage: int | None = None

    @property
    def execution_enabled(self) -> bool:
        return self.config.execution_enabled

    async def connect(self) -> None:
        await self._rest_snapshot()
        live_readonly = bool(getattr(self.connector, "read_only", False))
        has_user_stream = bool(getattr(self.connector, "has_user_stream", False))
        if live_readonly and not has_user_stream:
            self.store.mark_ws(False)
            self.connected = True
            self.recovery_reason = (
                self.recovery_reason
                or "NOT VERIFIED — credentials required for authenticated read-only validation"
            )
        else:
            self.store.mark_ws(True)
            self.connected = True

    async def disconnect(self) -> None:
        self.store.mark_ws(False)
        self.connected = False

    async def _rest_snapshot(self) -> None:
        snap = await self.connector.rest_snapshot()
        self.mid = Decimal(str(snap.get("mid", self.mid)))
        self.foreign_symbols = []
        self.one_way_ok = True
        self.recovery_reason = None
        try:
            positions, _reasons = map_clearinghouse_positions(
                snap.get("assetPositions") or [],
                configured_pair=self.config.trading_pair,
            )
        except OneWayError as exc:
            self.one_way_ok = False
            self.recovery_reason = str(exc)
            positions = []
        for pos in positions:
            if pos.symbol != self.config.trading_pair:
                self.foreign_symbols.append(pos.symbol)
            if pos.leverage is not None:
                self.observed_leverage = pos.leverage
        if self.foreign_symbols:
            self.recovery_reason = self.recovery_reason or "foreign position present"
        if self.observed_leverage is not None and self.observed_leverage != self.config.expected_leverage:
            self.leverage_mismatch = True
        else:
            self.leverage_mismatch = False
        orders = [
            map_hummingbot_order(item, configured_pair=self.config.trading_pair)
            for item in snap.get("openOrders") or []
        ]
        fills = [
            map_hummingbot_fill(item, configured_pair=self.config.trading_pair)
            for item in snap.get("fills") or []
        ]
        self.store.resync_from_rest(positions=positions, orders=orders, fills=fills)
        hb_raw = snap.get("hummingbotPositions")
        if hb_raw is not None:
            try:
                hb_positions, _ = map_clearinghouse_positions(
                    hb_raw,
                    configured_pair=self.config.trading_pair,
                )
            except OneWayError as exc:
                self.one_way_ok = False
                self.recovery_reason = str(exc)
                hb_positions = []
            mismatch = compare_rest_and_hummingbot(positions, hb_positions)
            if mismatch:
                self.store.mark_conflict(mismatch)
                self.recovery_reason = mismatch

    def worker_state(self) -> WorkerState:
        if not self.connected:
            return WorkerState.NOT_READY
        if not self.store.ws_connected:
            return WorkerState.DEGRADED
        if self.store.needs_reconciliation or not self.one_way_ok or self.foreign_symbols:
            return WorkerState.RECOVERING
        return WorkerState.READY

    async def get_balance(self) -> BalanceView:
        snap = await self.connector.rest_snapshot()
        acct = snap.get("account") or {}
        return BalanceView(
            equity=Decimal(str(acct.get("equity", "0"))),
            available=Decimal(str(acct.get("available", "0"))),
            margin_used=Decimal(str(acct.get("margin_used", "0"))),
        )

    async def get_available_balance(self) -> Decimal:
        return (await self.get_balance()).available

    async def get_positions(self) -> list[PositionView]:
        return [
            PositionView(
                symbol=item.symbol,
                side=item.side,
                size=item.size,
                entry_price=item.entry_price,
                unrealized_pnl=item.unrealized_pnl,
            )
            for item in self.store.positions.values()
            if item.side != PositionSide.FLAT
        ]

    async def get_position(self, symbol: str) -> PositionView:
        item = self.store.positions.get(symbol)
        if item is None:
            return PositionView(symbol=symbol, side=PositionSide.FLAT, size=Decimal("0"))
        return PositionView(
            symbol=item.symbol,
            side=item.side,
            size=item.size,
            entry_price=item.entry_price,
            unrealized_pnl=item.unrealized_pnl,
        )

    async def get_open_orders(self, symbol: str | None = None) -> list[OrderView]:
        rows = [
            self._order_view(item)
            for item in self.store.orders.values()
            if item.status in {OrderStatus.OPEN, OrderStatus.PARTIAL}
        ]
        if symbol:
            rows = [item for item in rows if item.symbol == symbol]
        return rows

    async def get_order(self, cloid: str) -> OrderView | None:
        raw = await self.connector.get_order(cloid)
        if raw is None:
            stored = self.store.orders.get(cloid)
            return self._order_view(stored) if stored else None
        mapped = map_hummingbot_order(raw, configured_pair=self.config.trading_pair)
        return self._order_view(mapped)

    async def get_fills(self) -> list[FillView]:
        raw = await self.connector.get_fills()
        return [
            FillView(
                fill_id=item.fill_id,
                cloid=item.cloid,
                symbol=item.symbol,
                side=item.side,
                price=item.price,
                quantity=item.quantity,
                fee=item.fee,
            )
            for item in (map_hummingbot_fill(row, configured_pair=self.config.trading_pair) for row in raw)
        ]

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        if getattr(self.connector, "read_only", False) or not self.config.execution_enabled:
            raise ExecutionDisabled("set_leverage blocked: execution disabled or read-only")
        await self.connector.set_leverage(symbol, leverage)

    async def get_market_data(self, symbol: str) -> dict[str, Decimal]:
        _ = symbol
        return {"mid": self.mid, "bid": self.mid - self.meta.tick_size, "ask": self.mid + self.meta.tick_size}

    def _ioc_price(self, request: PlaceOrderRequest) -> Decimal:
        if request.price is not None:
            return request.price
        return ioc_limit_price(
            side=request.side,
            mid=self.mid,
            slippage=self.config.slippage,
            tick=self.meta.tick_size,
        )

    async def place_order(self, request: PlaceOrderRequest) -> PlaceOrderResponse:
        if request.cloid in self._submitted_cloids:
            existing = await self.get_order(request.cloid)
            if existing is not None:
                return PlaceOrderResponse(
                    request_id=request.request_id,
                    cloid=request.cloid,
                    exchange_oid=existing.exchange_oid,
                    status=existing.status,
                    filled_quantity=existing.filled_quantity,
                    avg_price=existing.price,
                    error="duplicate cloid not resubmitted",
                )
            return PlaceOrderResponse(
                request_id=request.request_id,
                cloid=request.cloid,
                status=OrderStatus.UNKNOWN,
                error="duplicate cloid; previous result unconfirmed; will not resubmit",
            )
        try:
            price = self._ioc_price(request)
            normalized = normalize_order_request(request, self.meta, price)
        except QuantizeReject as exc:
            return PlaceOrderResponse(
                request_id=request.request_id,
                cloid=request.cloid,
                status=OrderStatus.REJECTED,
                error=str(exc),
            )
        self.last_normalized = normalized
        tif = "Ioc" if normalized.order_type == OrderType.MARKET else "Gtc"
        wire = {
            "cloid": normalized.cloid,
            "symbol": normalized.symbol,
            "is_buy": normalized.side == OrderSide.BUY,
            "sz": str(normalized.quantity),
            "limit_px": str(normalized.price),
            "reduce_only": normalized.reduce_only,
            "tif": tif,
            "order_type": normalized.order_type.value,
        }
        self.last_wire = wire
        if getattr(self.connector, "read_only", False) or not self.config.execution_enabled:
            if getattr(self.connector, "read_only", False):
                return PlaceOrderResponse(
                    request_id=request.request_id,
                    cloid=request.cloid,
                    status=OrderStatus.REJECTED,
                    error="read-only connector; place/cancel/leverage forbidden",
                )
            return PlaceOrderResponse(
                request_id=request.request_id,
                cloid=request.cloid,
                status=OrderStatus.REJECTED,
                error="execution disabled (DRY_RUN); connector was not called",
            )
        self._submitted_cloids.add(request.cloid)
        result = await self.connector.place(wire)
        raw = result.get("order") or {}
        mapped = map_hummingbot_order(raw, configured_pair=self.config.trading_pair)
        self.store.apply_ws_order(mapped)
        return PlaceOrderResponse(
            request_id=request.request_id,
            cloid=request.cloid,
            exchange_oid=mapped.exchange_order_id,
            status=mapped.status,
            filled_quantity=mapped.filled_quantity,
            avg_price=mapped.price,
        )

    async def open_long(self, request: PlaceOrderRequest) -> PlaceOrderResponse:
        return await self.place_order(
            request.model_copy(update={"side": OrderSide.BUY, "reduce_only": False, "command": "open_long"})
        )

    async def open_short(self, request: PlaceOrderRequest) -> PlaceOrderResponse:
        return await self.place_order(
            request.model_copy(update={"side": OrderSide.SELL, "reduce_only": False, "command": "open_short"})
        )

    async def close_position(self, request: PlaceOrderRequest) -> PlaceOrderResponse:
        return await self.place_order(request.model_copy(update={"reduce_only": True, "command": "close_position"}))

    async def cancel_order(self, cloid: str, request_id: str) -> OrderView | None:
        _ = request_id
        if getattr(self.connector, "read_only", False) or not self.config.execution_enabled:
            raise ExecutionDisabled("cancel_order blocked: execution disabled or read-only")
        await self.connector.cancel(cloid)
        return await self.get_order(cloid)

    async def stream_events(self):
        yield {
            "type": "hello",
            "mode": "hyperliquid",
            "execution_enabled": self.config.execution_enabled,
            "hummingbot_version": self.config.hummingbot_version,
        }

    def _order_view(self, item) -> OrderView:
        return OrderView(
            cloid=item.cloid,
            exchange_oid=item.exchange_order_id,
            symbol=item.symbol,
            side=item.side,
            order_type=item.order_type,
            quantity=item.quantity,
            filled_quantity=item.filled_quantity,
            reduce_only=item.reduce_only,
            status=item.status,
            price=item.price,
        )
