from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from app.config import WorkerConfig
from app.factory import build_runtime
from app.hyperliquid_adapter import ExecutionDisabled
from app.protocol import OrderSide, OrderType, PlaceOrderRequest, OrderStatus


def _request(*, reduce_only: bool = False) -> PlaceOrderRequest:
    return PlaceOrderRequest(
        request_id="heartbeat-test",
        cloid="0x" + "a" * 32,
        symbol="BTC-USD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("10"),
        reduce_only=reduce_only,
    )


def test_stale_backend_heartbeat_rejects_new_open() -> None:
    async def exercise() -> None:
        runtime = build_runtime(
            WorkerConfig(
                mode="mock",
                execution_enabled=True,
                trading_pair="BTC-USD",
                backend_heartbeat_timeout_seconds=0.01,
            )
        )
        await runtime.connect()
        assert runtime.health_payload()["ready"] is False
        assert runtime.health_payload()["worker_state"] == "DEGRADED"
        await asyncio.sleep(0.02)
        response = await runtime.place_order(_request())
        assert response.status == OrderStatus.REJECTED
        assert response.error == "backend heartbeat expired; new opens forbidden"

        runtime.heartbeat()
        assert runtime.health_payload()["ready"] is True
        assert runtime.health_payload()["worker_state"] == "READY"
        response = await runtime.place_order(_request())
        assert response.status == OrderStatus.FILLED

    asyncio.run(exercise())


def test_stale_backend_heartbeat_rejects_leverage_update() -> None:
    async def exercise() -> None:
        runtime = build_runtime(
            WorkerConfig(mode="mock", execution_enabled=True, trading_pair="BTC-USD")
        )
        await runtime.connect()
        with pytest.raises(ExecutionDisabled, match="heartbeat"):
            await runtime.set_leverage("BTC-USD", 3)
        runtime.heartbeat()
        await runtime.set_leverage("BTC-USD", 3)

    asyncio.run(exercise())
