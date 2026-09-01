from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app as worker_app
from app.mock_adapter import MockExecutionAdapter, PlaceBehavior
from app.protocol import OrderSide, OrderType, PlaceOrderRequest


@pytest.mark.asyncio
async def test_mock_fill_and_position() -> None:
    adapter = MockExecutionAdapter()
    await adapter.connect()
    result = await adapter.place_order(
        PlaceOrderRequest(
            request_id="r1",
            cloid="0x" + "a" * 32,
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1,
        )
    )
    assert result.status.value == "FILLED"
    pos = await adapter.get_position("BTC-USD")
    assert pos.side.value == "LONG"


@pytest.mark.asyncio
async def test_mock_unknown_modes() -> None:
    adapter = MockExecutionAdapter()
    await adapter.connect()
    adapter.set_behavior(PlaceBehavior.NETWORK_BEFORE_ACCEPT.value)
    with pytest.raises(TimeoutError):
        await adapter.place_order(
            PlaceOrderRequest(
                request_id="r2",
                cloid="0x" + "b" * 32,
                symbol="BTC-USD",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=1,
            )
        )
    assert await adapter.get_order("0x" + "b" * 32) is None

    adapter.set_behavior(PlaceBehavior.TIMEOUT_AFTER_ACCEPT.value)
    with pytest.raises(TimeoutError):
        await adapter.place_order(
            PlaceOrderRequest(
                request_id="r3",
                cloid="0x" + "c" * 32,
                symbol="BTC-USD",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=1,
            )
        )
    assert await adapter.get_order("0x" + "c" * 32) is not None


@pytest.mark.asyncio
async def test_worker_health_http() -> None:
    async with AsyncClient(transport=ASGITransport(app=worker_app), base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["mode"] == "mock"
        assert response.json()["execution_enabled"] is False


@pytest.mark.asyncio
async def test_open_long_helper_and_stream() -> None:
    adapter = MockExecutionAdapter()
    await adapter.connect()
    result = await adapter.open_long(
        PlaceOrderRequest(
            request_id="r4",
            cloid="0x" + "d" * 32,
            symbol="BTC-USD",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=1,
        )
    )
    assert result.status.value == "FILLED"
    pos = await adapter.get_position("BTC-USD")
    assert pos.side.value == "LONG"
    events = [item async for item in adapter.stream_events()]
    assert events[0]["mode"] == "mock"
