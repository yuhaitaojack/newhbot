from __future__ import annotations

from decimal import Decimal

import pytest

from app.config import WorkerConfig
from app.connector_bridge import FakeConnector
from app.hyperliquid_adapter import ExecutionDisabled, HyperliquidExecutionAdapter
from app.protocol import OrderSide, OrderStatus, OrderType, PlaceOrderRequest
from app.runtime import WorkerRuntime
from app.state_store import ExchangeStateStore
from app.exchange_models import ExchangeOrder, ExchangePosition
from app.protocol import PositionSide, OrderStatus as OS
from app.mapping import map_hummingbot_position


def _cfg(**kwargs) -> WorkerConfig:
    data = dict(mode="hyperliquid", execution_enabled=False, trading_pair="BTC-USD")
    data.update(kwargs)
    return WorkerConfig(**data)


def _req(**kwargs) -> PlaceOrderRequest:
    payload = dict(
        request_id="r1",
        cloid="0x" + "b" * 32,
        symbol="BTC-USD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.2"),
        reduce_only=False,
    )
    payload.update(kwargs)
    return PlaceOrderRequest(**payload)


@pytest.mark.asyncio
async def test_dry_run_never_calls_connector() -> None:
    connector = FakeConnector()
    adapter = HyperliquidExecutionAdapter(_cfg(execution_enabled=False), connector)
    await adapter.connect()
    result = await adapter.place_order(_req())
    assert result.status == OrderStatus.REJECTED
    assert "execution disabled" in (result.error or "")
    assert connector.place_calls == 0
    assert adapter.last_wire is not None
    assert adapter.last_wire["cloid"] == "0x" + "b" * 32


@pytest.mark.asyncio
async def test_enabled_place_uses_our_cloid_and_no_resubmit() -> None:
    connector = FakeConnector()
    adapter = HyperliquidExecutionAdapter(_cfg(execution_enabled=True), connector)
    await adapter.connect()
    first = await adapter.place_order(_req())
    assert first.status == OrderStatus.FILLED
    assert connector.place_calls == 1
    second = await adapter.place_order(_req())
    assert connector.place_calls == 1
    assert "not resubmitted" in (second.error or "") or second.status == OrderStatus.FILLED


@pytest.mark.asyncio
async def test_place_exception_marks_unknown_and_does_not_retry() -> None:
    connector = FakeConnector()
    connector.raise_on_place = True
    adapter = HyperliquidExecutionAdapter(_cfg(execution_enabled=True), connector)
    await adapter.connect()
    with pytest.raises(TimeoutError):
        await adapter.place_order(_req())
    assert connector.place_calls == 1
    connector.raise_on_place = False
    again = await adapter.place_order(_req())
    assert connector.place_calls == 1
    assert again.status == OrderStatus.UNKNOWN or "will not resubmit" in (again.error or "")


@pytest.mark.asyncio
async def test_reduce_only_close_sides() -> None:
    connector = FakeConnector()
    adapter = HyperliquidExecutionAdapter(_cfg(execution_enabled=False), connector)
    await adapter.connect()
    long_close = await adapter.place_order(_req(side=OrderSide.SELL, reduce_only=True, command="close_position"))
    assert long_close.status == OrderStatus.REJECTED
    assert adapter.last_wire["is_buy"] is False
    assert adapter.last_wire["reduce_only"] is True
    short_close = await adapter.place_order(_req(side=OrderSide.BUY, reduce_only=True, cloid="0x" + "c" * 32))
    assert adapter.last_wire["is_buy"] is True
    assert adapter.last_wire["reduce_only"] is True


@pytest.mark.asyncio
async def test_symbol_gate_and_not_ready() -> None:
    runtime = WorkerRuntime(HyperliquidExecutionAdapter(_cfg(), FakeConnector()), _cfg())
    rejected = await runtime.place_order(_req(symbol="ETH-USD"))
    assert rejected.status == OrderStatus.REJECTED
    assert "trading pair" in (rejected.error or "")
    not_ready = await runtime.place_order(_req())
    assert not_ready.status == OrderStatus.REJECTED
    assert "READY" in (not_ready.error or "")


@pytest.mark.asyncio
async def test_leverage_interface_blocked_when_disabled() -> None:
    adapter = HyperliquidExecutionAdapter(_cfg(execution_enabled=False), FakeConnector())
    with pytest.raises(ExecutionDisabled):
        await adapter.set_leverage("BTC-USD", 5)


@pytest.mark.asyncio
async def test_foreign_position_recovery() -> None:
    connector = FakeConnector()
    connector.asset_positions = [
        {
            "type": "oneWay",
            "position": {
                "coin": "ETH",
                "szi": "1",
                "entryPx": "2000",
                "unrealizedPnl": "0",
                "leverage": {"value": "1"},
            },
        }
    ]
    adapter = HyperliquidExecutionAdapter(_cfg(), connector)
    await adapter.connect()
    assert adapter.foreign_symbols
    assert adapter.worker_state().value == "RECOVERING"


@pytest.mark.asyncio
async def test_ws_disconnect_resync() -> None:
    store = ExchangeStateStore()
    store.apply_rest_snapshot(
        positions=[
            ExchangePosition(symbol="BTC-USD", side=PositionSide.FLAT, size=Decimal("0")),
        ],
        orders=[],
    )
    store.apply_ws_order(
        ExchangeOrder(
            cloid="0x" + "d" * 32,
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            remaining_quantity=Decimal("1"),
            status=OS.OPEN,
        )
    )
    assert store.orders["0x" + "d" * 32].status == OS.OPEN
    store.apply_ws_position(
        map_hummingbot_position({"coin": "BTC", "szi": "1", "entryPx": "100", "unrealizedPnl": "0", "leverage": {"value": "1"}}, configured_pair="BTC-USD")
    )
    assert store.positions["BTC-USD"].side == PositionSide.LONG
    store.mark_ws(False)
    store.resync_from_rest(
        positions=[
            map_hummingbot_position({"coin": "BTC", "szi": "1", "entryPx": "100", "unrealizedPnl": "0", "leverage": {"value": "1"}}, configured_pair="BTC-USD")
        ],
        orders=[],
    )
    assert store.positions["BTC-USD"].side == PositionSide.LONG
    assert store.needs_reconciliation is False


@pytest.mark.asyncio
async def test_rest_ws_side_conflict_does_not_silent_overwrite() -> None:
    store = ExchangeStateStore()
    store.apply_rest_snapshot(
        positions=[
            map_hummingbot_position({"coin": "BTC", "szi": "1", "entryPx": "100", "unrealizedPnl": "0", "leverage": {"value": "1"}}, configured_pair="BTC-USD")
        ],
        orders=[],
    )
    store.apply_ws_position(
        map_hummingbot_position({"coin": "BTC", "szi": "-1", "entryPx": "100", "unrealizedPnl": "0", "leverage": {"value": "1"}}, configured_pair="BTC-USD")
    )
    assert store.needs_reconciliation is True
    assert store.positions["BTC-USD"].side == PositionSide.LONG
