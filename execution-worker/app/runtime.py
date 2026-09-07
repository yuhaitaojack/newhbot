from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import time

from app.config import WorkerConfig
from app.exchange_models import SyncStatus, WorkerState
from app.hyperliquid_adapter import ExecutionDisabled
from app.protocol import PlaceOrderRequest, PlaceOrderResponse, OrderStatus


class WorkerRuntime:
    """Wraps Mock or Hyperliquid adapter. Enforces pair, readiness, and no extra retries."""

    def __init__(self, inner, config: WorkerConfig) -> None:
        self.inner = inner
        self.config = config
        self.state = WorkerState.NOT_READY
        self._force_degraded = False
        self._last_backend_heartbeat: float | None = None

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

    def _sync_status_value(self) -> str:
        getter = getattr(self.inner, "sync_status", None)
        if callable(getter):
            status = getter()
            return getattr(status, "value", str(status))
        if self.state == WorkerState.READY:
            return SyncStatus.LIVE.value
        if self.state == WorkerState.DEGRADED:
            return SyncStatus.RESYNC.value
        if self.state == WorkerState.RECOVERING:
            return SyncStatus.CONFLICT.value
        return SyncStatus.NONE.value

    def health_payload(self) -> dict:
        self._refresh_state()
        connector = getattr(self.inner, "connector", None)
        heartbeat_ok = self.backend_heartbeat_ok
        ready = self.ready and heartbeat_ok
        worker_state = self.state.value if heartbeat_ok else WorkerState.DEGRADED.value
        sync_status = self._sync_status_value() if heartbeat_ok else SyncStatus.RESYNC.value
        return {
            "status": "ok",
            "mode": self.config.mode,
            "hyperliquid_domain": self.config.hyperliquid_domain if self.config.is_hyperliquid else None,
            "connected": bool(getattr(self.inner, "connected", False)),
            "ready": ready,
            "worker_state": worker_state,
            "execution_enabled": self.config.execution_enabled,
            "trading_pair": self.config.trading_pair,
            "ws_connected": bool(getattr(connector, "ws_connected", ready)),
            "sync_status": sync_status,
            "hummingbot_version": self.config.hummingbot_version,
            "recovery_reason": getattr(self.inner, "recovery_reason", None),
            "foreign_symbols": getattr(self.inner, "foreign_symbols", []),
            "backend_heartbeat_ok": self.backend_heartbeat_ok,
        }

    @property
    def backend_heartbeat_ok(self) -> bool:
        if not self.config.execution_enabled:
            return True
        if self._last_backend_heartbeat is None:
            return False
        return (
            time.monotonic() - self._last_backend_heartbeat
            <= self.config.backend_heartbeat_timeout_seconds
        )

    def heartbeat(self) -> None:
        self._last_backend_heartbeat = time.monotonic()

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
        if not request.reduce_only and not self.backend_heartbeat_ok:
            return PlaceOrderResponse(
                request_id=request.request_id,
                cloid=request.cloid,
                status=OrderStatus.REJECTED,
                error="backend heartbeat expired; new opens forbidden",
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
        if self.config.execution_enabled:
            self._refresh_state()
            if self.state != WorkerState.READY:
                raise ExecutionDisabled(f"worker is {self.state.value}; leverage update forbidden")
            if not self.backend_heartbeat_ok:
                raise ExecutionDisabled("backend heartbeat expired; leverage update forbidden")
        await self.inner.set_leverage(symbol, leverage)

    async def cancel_order(self, cloid: str, request_id: str):
        return await self.inner.cancel_order(cloid, request_id)

    def mark_ws_down(self) -> None:
        self._force_degraded = True
        marker = getattr(self.inner, "mark_network_down", None)
        if callable(marker):
            marker()
        self._refresh_state()

    async def rest_resync(self) -> None:
        self._force_degraded = False
        resync = getattr(self.inner, "resync_network", None)
        if callable(resync):
            await resync()
        elif getattr(self.inner, "connected", False):
            self.state = WorkerState.READY
        self._refresh_state()

    def __getattr__(self, name: str):
        return getattr(self.inner, name)
