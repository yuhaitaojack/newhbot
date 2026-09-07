from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.hummingbot_readonly import (
    ReadOnlyHummingbotBridge,
    disable_exchange_write_loops,
    _asset_from_hb_position,
)
from app.readonly_guard import ReadOnlyViolation


def test_asset_from_hb_position_long_and_short() -> None:
    long_pos = SimpleNamespace(
        trading_pair="BTC-USD",
        position_side="PositionSide.LONG",
        amount=Decimal("0.5"),
        entry_price=Decimal("100"),
        unrealized_pnl=Decimal("1"),
        leverage=Decimal("3"),
    )
    short_pos = SimpleNamespace(
        trading_pair="ETH-USD",
        position_side="PositionSide.SHORT",
        amount=Decimal("2"),
        entry_price=Decimal("2000"),
        unrealized_pnl=Decimal("0"),
        leverage=Decimal("1"),
    )
    long_raw = _asset_from_hb_position(long_pos)
    short_raw = _asset_from_hb_position(short_pos)
    assert long_raw["position"]["szi"] == "0.5"
    assert long_raw["position"]["coin"] == "BTC"
    assert short_raw["position"]["szi"] == "-2"
    assert short_raw["position"]["coin"] == "ETH"


class _StubConnector:
    def __init__(self) -> None:
        self.account_positions = {}
        self.in_flight_orders = {}
        self.trading_rules = {
            "BTC-USD": SimpleNamespace(
                min_base_amount_increment=Decimal("0.00001"),
                min_price_increment=Decimal("0.1"),
                min_order_size=Decimal("0.00001"),
                min_notional_size=Decimal("10"),
            )
        }
        self._trading_pairs = ["BTC-USD"]
        self.started = False

    async def start_network(self) -> None:
        self.started = True

    async def stop_network(self) -> None:
        self.started = False

    def add_listener(self, event, cb) -> None:
        _ = event, cb

    def quantize_order_price(self, trading_pair: str, price: Decimal) -> Decimal:
        _ = trading_pair
        return price

    def quantize_order_amount(self, trading_pair: str, amount: Decimal) -> Decimal:
        _ = trading_pair
        return amount

    def buy(self, *args, **kwargs):
        raise AssertionError("buy must be guarded")

    def sell(self, *args, **kwargs):
        raise AssertionError("sell must be guarded")

    def _place_order(self, *args, **kwargs):
        raise AssertionError("_place_order must be guarded")

    async def _place_cancel(self, *args, **kwargs):
        raise AssertionError("_place_cancel must be guarded")


@pytest.mark.asyncio
async def test_readonly_bridge_uses_connector_rules_and_blocks_trading() -> None:
    stub = _StubConnector()
    bridge = ReadOnlyHummingbotBridge(stub)
    await bridge.start_network()
    assert stub.started is True
    assert bridge.ws_connected is True
    rule = bridge.trading_rule("BTC-USD")
    assert rule.tick_size == Decimal("0.1")
    assert rule.min_notional == Decimal("10")
    with pytest.raises(ReadOnlyViolation):
        await bridge.place({"cloid": "0x" + "a" * 32})
    with pytest.raises(ReadOnlyViolation):
        await bridge.cancel("0x" + "a" * 32)
    with pytest.raises(ReadOnlyViolation):
        await bridge.set_leverage("BTC-USD", 2)
    with pytest.raises(ReadOnlyViolation):
        stub_via_guard = bridge.connector
        stub_via_guard.buy("BTC-USD", Decimal("1"))
    snap = await bridge.rest_snapshot()
    assert snap["account_read"] == "skipped_no_user_address"
    assert snap["fills"] == []
    assert snap["assetPositions"] == []


@pytest.mark.asyncio
async def test_disable_write_loops_noops_lost_order_cancel() -> None:
    stub = _StubConnector()
    cancelled = {"n": 0}

    async def _cancel_lost_orders() -> None:
        cancelled["n"] += 1

    async def _execute_order_cancel(*_a, **_k) -> None:
        cancelled["n"] += 10

    stub._cancel_lost_orders = _cancel_lost_orders
    stub._execute_order_cancel = _execute_order_cancel
    disable_exchange_write_loops(stub)
    await stub._cancel_lost_orders()
    assert cancelled["n"] == 0
    with pytest.raises(ReadOnlyViolation):
        await stub._execute_order_cancel()
    with pytest.raises(ReadOnlyViolation):
        stub.buy("BTC-USD", Decimal("1"))
    with pytest.raises(ReadOnlyViolation):
        stub.sell("BTC-USD", Decimal("1"))
    with pytest.raises(ReadOnlyViolation):
        await stub._place_order()
    with pytest.raises(ReadOnlyViolation):
        stub.set_leverage("BTC-USD", 2)
    assert callable(getattr(stub, "_newhbot_original_place_order", None))


@pytest.mark.asyncio
async def test_authenticated_bridge_reads_connector_positions_and_still_blocks() -> None:
    stub = _StubConnector()
    stub.account_positions = {
        "BTC-USD": SimpleNamespace(
            trading_pair="BTC-USD",
            position_side="PositionSide.LONG",
            amount=Decimal("0.1"),
            entry_price=Decimal("65000"),
            unrealized_pnl=Decimal("1"),
            leverage=Decimal("2"),
        )
    }
    stub._current_trade_fills = [
        {
            "tid": "99",
            "oid": 1,
            "cloid": "0x" + "c" * 32,
            "coin": "BTC",
            "side": "B",
            "px": "65000",
            "sz": "0.1",
            "fee": "0",
        }
    ]

    async def _update_positions() -> None:
        return None

    async def _update_balances() -> None:
        stub._account_balances = {"USD": Decimal("19.4")}
        stub._account_available_balances = {"USD": Decimal("18.1")}

    stub._update_positions = _update_positions
    stub._update_balances = _update_balances
    stub._user_stream_event_listener_task = object()
    bridge = ReadOnlyHummingbotBridge(stub, authenticated=True)
    await bridge.start_network()
    assert bridge.authenticated is True
    assert bridge.account_read == "authenticated"
    snap = await bridge.rest_snapshot()
    assert snap["assetPositions"][0]["position"]["coin"] == "BTC"
    assert snap["assetPositions"][0]["position"]["szi"] == "0.1"
    assert snap["fills"][0]["tid"] == "99"
    assert snap["account"]["equity"] == "19.4"
    assert snap["account"]["available"] == "18.1"
    assert snap["account"]["quote"] == "USD"
    with pytest.raises(ReadOnlyViolation):
        await bridge.place({"cloid": "0x" + "a" * 32})
    with pytest.raises(ReadOnlyViolation):
        await stub._execute_order_cancel()


@pytest.mark.asyncio
async def test_bridge_reads_fills_from_tracked_hyperliquid_orders() -> None:
    stub = _StubConnector()
    cloid = "0x" + "f" * 32
    trade_update = SimpleNamespace(
        trade_id="trade-1",
        client_order_id=cloid,
        exchange_order_id="17",
        trading_pair="BTC-USD",
        trade_type="SELL",
        fill_price=Decimal("65000"),
        fill_base_amount=Decimal("0.00014"),
        fill_quote_amount=Decimal("9.1"),
        fill_timestamp=1.0,
        exchange_trade_id="trade-1",
        fee=None,
    )
    tracked = SimpleNamespace(order_fills={"trade-1": trade_update})
    stub._order_tracker = SimpleNamespace(all_fillable_orders={cloid: tracked})
    bridge = ReadOnlyHummingbotBridge(stub, authenticated=True)

    fills = await bridge.get_fills()

    assert fills == [
        {
            "tid": "trade-1",
            "oid": "17",
            "cloid": cloid,
            "coin": "BTC",
            "symbol": "BTC-USD",
            "side": "SELL",
            "px": "65000",
            "sz": "0.00014",
            "fee": "0",
            "hash": "trade-1",
        }
    ]


@pytest.mark.asyncio
async def test_armed_authenticated_bridge_cancels_only_matching_business_cloid() -> None:
    stub = _StubConnector()
    cloid = "0x" + "d" * 32
    tracked = SimpleNamespace(
        client_order_id=cloid,
        exchange_order_id="17",
        trading_pair="BTC-USD",
        base_asset="BTC",
        trade_type="BUY",
        amount=Decimal("0.1"),
        executed_amount_base=Decimal("0"),
        price=Decimal("65000"),
        position="OPEN",
        is_open=True,
        is_cancelled=False,
        is_filled=False,
        is_failure=False,
    )
    stub.in_flight_orders[cloid] = tracked
    calls: list[tuple[str, object]] = []

    async def _original_cancel(order_id: str, order: object) -> bool:
        calls.append((order_id, order))
        return True

    stub._place_cancel = _original_cancel
    stub._user_stream_event_listener_task = object()
    bridge = ReadOnlyHummingbotBridge(stub, authenticated=True, execution_enabled=True)
    result = await bridge.cancel(cloid)
    assert result["ok"] is True
    assert result["cloid"] == cloid
    assert calls == [(cloid, tracked)]
    with pytest.raises(ValueError):
        await bridge.cancel("not-a-business-cloid")


@pytest.mark.asyncio
async def test_armed_bridge_does_not_cancel_unknown_cloid() -> None:
    stub = _StubConnector()
    bridge = ReadOnlyHummingbotBridge(stub, authenticated=True, execution_enabled=True)
    result = await bridge.cancel("0x" + "e" * 32)
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_armed_authenticated_bridge_sets_leverage_through_saved_internal_seam() -> None:
    stub = _StubConnector()
    calls: list[tuple[str, int]] = []

    async def _original_leverage(symbol: str, leverage: int) -> tuple[bool, str]:
        calls.append((symbol, leverage))
        return True, ""

    stub._set_trading_pair_leverage = _original_leverage
    bridge = ReadOnlyHummingbotBridge(stub, authenticated=True, execution_enabled=True)
    await bridge.set_leverage("BTC-USD", 3)
    assert calls == [("BTC-USD", 3)]
    with pytest.raises(ReadOnlyViolation):
        await stub._set_trading_pair_leverage("BTC-USD", 4)


@pytest.mark.asyncio
async def test_authenticated_bridge_balance_failure_is_not_zero() -> None:
    stub = _StubConnector()

    async def _update_positions() -> None:
        return None

    async def _update_balances() -> None:
        raise TimeoutError("balance rest failed")

    stub._update_positions = _update_positions
    stub._update_balances = _update_balances
    stub._user_stream_event_listener_task = object()
    stub._account_balances = {}
    stub._account_available_balances = {}
    bridge = ReadOnlyHummingbotBridge(stub, authenticated=True)
    await bridge.start_network()
    assert bridge.account_read == "balance_query_failed"
    snap = await bridge.rest_snapshot()
    assert snap["account"] == {}
    assert "equity" not in snap["account"]


@pytest.mark.asyncio
async def test_unauthenticated_snapshot_does_not_invent_zero_account() -> None:
    stub = _StubConnector()
    bridge = ReadOnlyHummingbotBridge(stub)
    await bridge.start_network()
    snap = await bridge.rest_snapshot()
    assert snap["account_read"] == "skipped_no_user_address"
    assert snap["account"] == {}


class _RecordingPlaceStub(_StubConnector):
    def __init__(self) -> None:
        super().__init__()
        self.recorded: list[str] = []
        self.lost_cancel_n = 0

    async def _place_order(self, order_id: str, *args, **kwargs):
        self.recorded.append(str(order_id))
        return {"order": {"cloid": order_id, "oid": "1", "status": "open", "symbol": "BTC-USD", "side": "BUY"}}

    async def _cancel_lost_orders(self) -> None:
        self.lost_cancel_n += 1


@pytest.mark.asyncio
async def test_unarmed_bridge_still_forbids_place() -> None:
    stub = _RecordingPlaceStub()
    bridge = ReadOnlyHummingbotBridge(stub, authenticated=True, execution_enabled=False)
    with pytest.raises(ReadOnlyViolation):
        await bridge.place({"cloid": "0x" + "a" * 32})
    assert stub.recorded == []
    with pytest.raises(ReadOnlyViolation):
        await stub._place_order("0x" + "a" * 32)


@pytest.mark.asyncio
async def test_armed_bridge_place_uses_saved_original_and_keeps_other_locks() -> None:
    stub = _RecordingPlaceStub()
    bridge = ReadOnlyHummingbotBridge(stub, authenticated=True, execution_enabled=True)
    cloid = "0x" + "ab" * 16
    result = await bridge.place(
        {
            "cloid": cloid,
            "symbol": "BTC-USD",
            "is_buy": True,
            "sz": "0.2",
            "limit_px": "105.0",
            "reduce_only": False,
            "tif": "Ioc",
        }
    )
    assert stub.recorded == [cloid]
    assert result["order"]["cloid"] == cloid
    with pytest.raises(ReadOnlyViolation):
        await stub._place_order(cloid)
    with pytest.raises(ReadOnlyViolation):
        stub.buy("BTC-USD", Decimal("1"))
    with pytest.raises(ReadOnlyViolation):
        stub.sell("BTC-USD", Decimal("1"))
    assert (await bridge.cancel(cloid))["ok"] is False
    with pytest.raises(ReadOnlyViolation):
        await bridge.set_leverage("BTC-USD", 2)
    await stub._cancel_lost_orders()
    assert stub.lost_cancel_n == 0
    guarded = bridge.connector
    with pytest.raises(ReadOnlyViolation):
        guarded._place_order()
