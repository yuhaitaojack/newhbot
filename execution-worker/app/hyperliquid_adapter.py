from __future__ import annotations

import asyncio
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from decimal import Decimal

from app.config import HYPERLIQUID_INFO_URLS, WorkerConfig
from app.connector_bridge import ConnectorBridge, FakeConnector
from app.exchange_models import SyncStatus, WorkerState
from app.ioc_price import ioc_raw_price
from app.mapping import OneWayError, map_clearinghouse_positions, map_hummingbot_fill, map_hummingbot_order
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
from app.readonly_guard import ReadOnlyViolation


class ExecutionDisabled(RuntimeError):
    """Connector is wired but live place/cancel/leverage are forbidden."""


class HyperliquidExecutionAdapter:
    """Thin Adapter: business DTOs ↔ Hummingbot-shaped Connector.

    Execution-layer truth is the Connector (account_positions / in_flight_orders /
    fills / trading_rules / network). This class does not own a second order or
    position store.

    Default: execution_enabled=False. Code present ≠ live trading.
    Never calls connector.buy()/sell() (those mint a new MD5 cloid in v2.16.0).
    Never retries place() for the same cloid (UNKNOWN / duplicate set).
    """

    def __init__(
        self,
        config: WorkerConfig,
        connector: ConnectorBridge | None = None,
    ) -> None:
        self.config = config
        self.connector = connector or FakeConnector()
        self.connected = False
        self.recovery_reason: str | None = None
        self.foreign_symbols: list[str] = []
        self.one_way_ok = True
        self.last_normalized: PlaceOrderRequest | None = None
        self.last_wire: dict | None = None
        self._submitted_cloids: set[str] = set()
        self.mid = Decimal("100")
        self.leverage_mismatch = False
        self.observed_leverage: int | None = None
        self._candle_cache: dict[tuple[str, str, int], tuple[float, list[dict]]] = {}

    @property
    def execution_enabled(self) -> bool:
        return self.config.execution_enabled

    def _connector_ws_connected(self) -> bool:
        return bool(getattr(self.connector, "ws_connected", False))

    def _account_positions_trusted(self) -> bool:
        """Unauthenticated or failed account reads must not be treated as FLAT."""
        if bool(getattr(self.connector, "read_only", False)) and not bool(
            getattr(self.connector, "authenticated", False)
        ):
            return False
        account_read = str(getattr(self.connector, "account_read", "") or "")
        if "failed" in account_read or account_read in {
            "position_query_unavailable",
            "balance_query_unavailable",
        }:
            return False
        return True

    def mark_network_down(self) -> None:
        if hasattr(self.connector, "ws_connected"):
            self.connector.ws_connected = False

    async def resync_network(self) -> None:
        start = getattr(self.connector, "start_network", None)
        if callable(start):
            await start()
        await self._refresh_from_connector()

    async def connect(self) -> None:
        live_readonly = bool(getattr(self.connector, "read_only", False))
        start = getattr(self.connector, "start_network", None)
        start_error = None
        if callable(start):
            try:
                await start()
            except Exception as exc:
                start_error = str(exc)
        await self._refresh_from_connector()
        self.connected = True
        if start_error:
            self.recovery_reason = self.recovery_reason or f"connector start_network failed: {start_error}"
        account_read = str(getattr(self.connector, "account_read", "") or "")
        if "failed" in account_read or account_read in {
            "position_query_unavailable",
            "balance_query_unavailable",
        }:
            self.recovery_reason = self.recovery_reason or "account_state_unknown"
        authenticated = bool(getattr(self.connector, "authenticated", False))
        if live_readonly and not authenticated:
            self.recovery_reason = self.recovery_reason or (
                "read-only: no user address; authenticated positions/fills NOT VERIFIED"
            )

    async def _rest_snapshot(self) -> None:
        """Backward-compatible name; refreshes from Connector, not a Worker store."""
        await self._refresh_from_connector()

    async def disconnect(self) -> None:
        stop = getattr(self.connector, "stop_network", None)
        if callable(stop):
            await stop()
        self.connected = False

    async def _refresh_from_connector(self) -> list[PositionView]:
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
            self.recovery_reason = self.recovery_reason or "FOREIGN_SYMBOL_POSITION"
        account_read = str(snap.get("account_read") or getattr(self.connector, "account_read", "") or "")
        if "failed" in account_read or account_read in {
            "position_query_unavailable",
            "balance_query_unavailable",
        }:
            self.recovery_reason = self.recovery_reason or "account_state_unknown"
        if not self._account_positions_trusted():
            self.recovery_reason = self.recovery_reason or "authenticated account read unavailable"
        if self.observed_leverage is not None and self.observed_leverage != self.config.expected_leverage:
            self.leverage_mismatch = True
        else:
            self.leverage_mismatch = False
        return [
            PositionView(
                symbol=item.symbol,
                side=item.side,
                size=item.size,
                entry_price=item.entry_price,
                unrealized_pnl=item.unrealized_pnl,
            )
            for item in positions
            if item.side != PositionSide.FLAT
        ]

    def worker_state(self) -> WorkerState:
        if not self.connected:
            return WorkerState.NOT_READY
        if not self._connector_ws_connected():
            return WorkerState.DEGRADED
        if not self.one_way_ok or self.foreign_symbols:
            return WorkerState.RECOVERING
        if not self._account_positions_trusted():
            return WorkerState.RECOVERING
        if self.recovery_reason == "account_state_unknown":
            return WorkerState.RECOVERING
        if bool(getattr(self.connector, "authenticated", False)) and not bool(
            getattr(self.connector, "has_user_stream", False)
        ):
            return WorkerState.RECOVERING
        return WorkerState.READY

    def sync_status(self) -> SyncStatus:
        state = self.worker_state()
        if state == WorkerState.READY:
            return SyncStatus.LIVE
        if state == WorkerState.DEGRADED:
            return SyncStatus.RESYNC
        if state == WorkerState.RECOVERING:
            return SyncStatus.CONFLICT
        return SyncStatus.NONE

    def _mapped_positions(self, raw_rows: list[dict]) -> list[PositionView]:
        try:
            positions, _ = map_clearinghouse_positions(
                raw_rows,
                configured_pair=self.config.trading_pair,
            )
        except OneWayError:
            return []
        return [
            PositionView(
                symbol=item.symbol,
                side=item.side,
                size=item.size,
                entry_price=item.entry_price,
                unrealized_pnl=item.unrealized_pnl,
            )
            for item in positions
            if item.side != PositionSide.FLAT
        ]

    async def get_balance(self) -> BalanceView:
        if not self._account_positions_trusted():
            raise LookupError("authenticated account balances unavailable")
        snap = await self.connector.rest_snapshot()
        acct = snap.get("account") or {}
        if "equity" not in acct or "available" not in acct:
            raise LookupError("authenticated account balances unavailable")
        return BalanceView(
            equity=Decimal(str(acct["equity"])),
            available=Decimal(str(acct["available"])),
            margin_used=Decimal(str(acct.get("margin_used", "0"))),
        )

    async def get_available_balance(self) -> Decimal:
        return (await self.get_balance()).available

    async def get_positions(self) -> list[PositionView]:
        rows = await self._refresh_from_connector()
        if not self._account_positions_trusted():
            raise LookupError("authenticated account read unavailable")
        return rows

    async def get_position(self, symbol: str) -> PositionView:
        for item in await self.get_positions():
            if item.symbol == symbol:
                return item
        return PositionView(symbol=symbol, side=PositionSide.FLAT, size=Decimal("0"))

    async def get_open_orders(self, symbol: str | None = None) -> list[OrderView]:
        snap = await self.connector.rest_snapshot()
        rows = [
            self._order_view(map_hummingbot_order(item, configured_pair=self.config.trading_pair))
            for item in snap.get("openOrders") or []
        ]
        rows = [item for item in rows if item.status in {OrderStatus.OPEN, OrderStatus.PARTIAL}]
        if symbol:
            rows = [item for item in rows if item.symbol == symbol]
        return rows

    async def get_order(self, cloid: str) -> OrderView | None:
        raw = await self.connector.get_order(cloid)
        if raw is None:
            return None
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
        connector_readonly = bool(getattr(self.connector, "read_only", False))
        connector_armed = bool(getattr(self.connector, "execution_enabled", False))
        if (connector_readonly and not connector_armed) or not self.config.execution_enabled:
            raise ExecutionDisabled("set_leverage blocked: execution disabled or read-only")
        try:
            await self.connector.set_leverage(symbol, leverage)
        except ReadOnlyViolation as exc:
            raise ExecutionDisabled(str(exc)) from exc

    async def get_market_data(self, symbol: str) -> dict[str, Decimal]:
        # A live connector can complete an account snapshot before its first
        # usable ticker is available. Refresh once so a transient zero mid does
        # not reject an otherwise valid Controller signal; callers still reject
        # the result if the refreshed snapshot has no usable price.
        if self.mid <= 0:
            await self._refresh_from_connector()
        rule_fn = getattr(self.connector, "trading_rule", None)
        tick = Decimal("0.1")
        if callable(rule_fn):
            try:
                tick = rule_fn(symbol).tick_size
            except Exception:
                tick = Decimal("0.1")
        return {"mid": self.mid, "bid": self.mid - tick, "ask": self.mid + tick}

    async def get_candles(self, symbol: str, interval: str, limit: int = 200) -> list[dict]:
        """Read public Hyperliquid candleSnapshot data; never signs or writes."""
        allowed = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d", "3d", "1w", "1M"}
        if interval not in allowed:
            raise ValueError("unsupported candle interval")
        limit = max(2, min(int(limit), 5000))
        unit_ms = {"m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}
        if interval.endswith("M"):
            step = 30 * 86_400_000
        else:
            step = int(interval[:-1]) * unit_ms[interval[-1]]
        cache_key = (symbol, interval, limit)
        cached = self._candle_cache.get(cache_key)
        cache_ttl = min(30.0, max(5.0, step / 10_000.0))
        if cached is not None and time.monotonic() - cached[0] < cache_ttl:
            return list(cached[1])
        end = int(time.time() * 1000)
        body = json.dumps({"type": "candleSnapshot", "req": {
            "coin": symbol.removesuffix("-USD"), "interval": interval,
            "startTime": end - step * (limit + 1), "endTime": end,
        }}).encode("utf-8")

        def fetch() -> list[dict]:
            request = Request(
                HYPERLIQUID_INFO_URLS[self.config.hyperliquid_domain],
                data=body,
                headers={"Content-Type": "application/json"},
            )
            with urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))

        rows = None
        for attempt in range(2):
            try:
                rows = await asyncio.to_thread(fetch)
                break
            except (HTTPError, URLError, TimeoutError):
                if attempt == 1:
                    raise
                # Public candle reads are safe to retry once; do not turn a
                # transient upstream 5xx/transport failure into Recovery.
                await asyncio.sleep(0.25)
        assert rows is not None
        candles = [{"timestamp": row["t"], "open": row["o"], "high": row["h"], "low": row["l"], "close": row["c"], "volume": row["v"]} for row in rows[-limit:]]
        self._candle_cache[cache_key] = (time.monotonic(), candles)
        return list(candles)

    def _ioc_price(self, request: PlaceOrderRequest) -> Decimal:
        if request.price is not None:
            return request.price
        raw = ioc_raw_price(side=request.side, mid=self.mid, slippage=self.config.slippage)
        return self.connector.quantize_order_price(request.symbol, raw)

    def _normalize(self, request: PlaceOrderRequest, price: Decimal) -> PlaceOrderRequest:
        qty = self.connector.quantize_order_amount(request.symbol, request.quantity)
        px = self.connector.quantize_order_price(request.symbol, price)
        rule = self.connector.trading_rule(request.symbol)
        if qty <= 0:
            raise ValueError("quantity quantized to zero")
        if qty < rule.min_order_size:
            raise ValueError("quantity below exchange minimum")
        min_notional = rule.min_notional
        # Closing must remain possible for dust/partial positions below the
        # normal entry minimum; never apply the entry threshold to reduce-only.
        if not request.reduce_only and qty * px < min_notional:
            raise ValueError(f"notional {qty * px} below minimum {min_notional}")
        return request.model_copy(update={"quantity": qty, "price": px})

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
            normalized = self._normalize(request, price)
        except ValueError as exc:
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
        if not self.config.execution_enabled:
            return PlaceOrderResponse(
                request_id=request.request_id,
                cloid=request.cloid,
                status=OrderStatus.REJECTED,
                error="execution disabled (DRY_RUN); connector was not called",
            )
        connector_readonly = bool(getattr(self.connector, "read_only", False))
        connector_armed = bool(getattr(self.connector, "execution_enabled", False))
        if connector_readonly and not connector_armed:
            return PlaceOrderResponse(
                request_id=request.request_id,
                cloid=request.cloid,
                status=OrderStatus.REJECTED,
                error="read-only connector; place/cancel/leverage forbidden",
            )
        self._submitted_cloids.add(request.cloid)
        try:
            result = await self.connector.place(wire)
        except ReadOnlyViolation as exc:
            return PlaceOrderResponse(
                request_id=request.request_id,
                cloid=request.cloid,
                status=OrderStatus.REJECTED,
                error=str(exc),
            )
        raw = result.get("order") or {}
        mapped = map_hummingbot_order(raw, configured_pair=self.config.trading_pair)
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
        connector_readonly = bool(getattr(self.connector, "read_only", False))
        connector_armed = bool(getattr(self.connector, "execution_enabled", False))
        if (connector_readonly and not connector_armed) or not self.config.execution_enabled:
            raise ExecutionDisabled("cancel_order blocked: execution disabled or read-only")
        try:
            await self.connector.cancel(cloid)
        except ReadOnlyViolation as exc:
            raise ExecutionDisabled(str(exc)) from exc
        return await self.get_order(cloid)

    async def stream_events(self):
        recent = getattr(self.connector, "recent_events", None)
        yield {
            "type": "hello",
            "mode": "hyperliquid",
            "execution_enabled": self.config.execution_enabled,
            "hummingbot_version": self.config.hummingbot_version,
            "market_events": list(recent()) if callable(recent) else [],
        }
        snap = await self.connector.rest_snapshot()
        positions = self._mapped_positions(snap.get("assetPositions") or [])
        yield {
            "type": "connector_snapshot",
            "positions": [item.model_dump(mode="json") for item in positions],
            "open_orders": [
                self._order_view(map_hummingbot_order(item, configured_pair=self.config.trading_pair)).model_dump(
                    mode="json"
                )
                for item in snap.get("openOrders") or []
            ],
            "fills": [
                map_hummingbot_fill(row, configured_pair=self.config.trading_pair).model_dump(mode="json")
                for row in snap.get("fills") or []
            ],
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
