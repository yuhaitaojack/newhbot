from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.config import WorkerConfig
from app.exchange_models import WorkerState
from app.protocol import PlaceOrderRequest, PlaceOrderResponse, OrderStatus


class WorkerRuntime:
    """Wraps Mock or Hyperliquid adapter. Enforces pair, readiness, and no extra retries."""

    def __init__(self, inner, config: WorkerConfig) -> None:
        self.inner = inner
        self.config = config
        self.state = WorkerState.NOT_READY
        self._force_degraded = False

    def _refresh_state(self) -> None:
        if self._force_degraded:
            self.state = WorkerState.DEGRADED
            return
        inner_state = getattr(self.inner, "worker_state", None)
        if callable(inner_state):
            self.state = inner_state()
            return
        if getattr(self.inner, "connected", False):
            self.state = WorkerState.READY
        else:
            self.state = WorkerState.NOT_READY

    @property
    def ready(self) -> bool:
        self._refresh_state()
        return self.state == WorkerState.READY

    def health_payload(self) -> dict:
        self._refresh_state()
        inner_store = getattr(self.inner, "store", None)
        return {
            "status": "ok",
            "mode": self.config.mode,
            "connected": bool(getattr(self.inner, "connected", False)),
            "ready": self.ready,
            "worker_state": self.state.value,
            "execution_enabled": self.config.execution_enabled,
            "trading_pair": self.config.trading_pair,
            "ws_connected": bool(getattr(inner_store, "ws_connected", self.ready)),
            "sync_status": getattr(getattr(inner_store, "sync_status", None), "value", "NONE"),
            "hummingbot_version": self.config.hummingbot_version,
            "recovery_reason": getattr(self.inner, "recovery_reason", None),
            "foreign_symbols": getattr(self.inner, "foreign_symbols", []),
        }

    def configure(self, *, trading_pair: str, slippage: Decimal | None = None, leverage: int | None = None) -> None:
        kwargs = {"trading_pair": trading_pair}
        if slippage is not None:
            kwargs["slippage"] = slippage
        if leverage is not None:
            kwargs["expected_leverage"] = leverage
        self.config = replace(self.config, **kwargs)
        if hasattr(self.inner, "config"):
            self.inner.config = self.config

    async def connect(self) -> None:
        await self.inner.connect()
        self._refresh_state()

    async def disconnect(self) -> None:
        await self.inner.disconnect()
        self._refresh_state()

    def _reject_symbol(self, request: PlaceOrderRequest) -> PlaceOrderResponse | None:
        if request.symbol != self.config.trading_pair:
            return PlaceOrderResponse(
                request_id=request.request_id,
                cloid=request.cloid,
                status=OrderStatus.REJECTED,
                error="symbol is not the configured trading pair",
            )
        return None

    async def place_order(self, request: PlaceOrderRequest) -> PlaceOrderResponse:
        bad = self._reject_symbol(request)
        if bad:
            return bad
        self._refresh_state()
        if self.state != WorkerState.READY:
            return PlaceOrderResponse(
                request_id=request.request_id,
                cloid=request.cloid,
                status=OrderStatus.REJECTED,
                error=f"worker is {self.state.value}; new opens forbidden",
            )
        return await self.inner.place_order(request)

    async def open_long(self, request: PlaceOrderRequest) -> PlaceOrderResponse:
        return await self.place_order(request)

    async def open_short(self, request: PlaceOrderRequest) -> PlaceOrderResponse:
        return await self.place_order(request)

    async def close_position(self, request: PlaceOrderRequest) -> PlaceOrderResponse:
        return await self.place_order(request)

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        if symbol != self.config.trading_pair:
            raise ValueError("symbol is not the configured trading pair")
        await self.inner.set_leverage(symbol, leverage)

    async def cancel_order(self, cloid: str, request_id: str):
        return await self.inner.cancel_order(cloid, request_id)

    def mark_ws_down(self) -> None:
        self._force_degraded = True
        store = getattr(self.inner, "store", None)
        if store is not None:
            store.mark_ws(False)
        self._refresh_state()

    async def rest_resync(self) -> None:
        self._force_degraded = False
        snap = getattr(self.inner, "_rest_snapshot", None)
        if callable(snap):
            await snap()
            store = getattr(self.inner, "store", None)
            if store is not None:
                store.mark_ws(True)
        elif getattr(self.inner, "connected", False):
            self.state = WorkerState.READY
        self._refresh_state()

    def __getattr__(self, name: str):
        return getattr(self.inner, name)
