from __future__ import annotations

import ast
import json
from pathlib import Path
from decimal import Decimal

import pytest

from app.config import WorkerConfig
from app.connector_bridge import FakeConnector
from app.hyperliquid_adapter import ExecutionDisabled, HyperliquidExecutionAdapter
from app.protocol import OrderSide, OrderStatus, OrderType, PlaceOrderRequest
from app.runtime import WorkerRuntime


ADAPTER_PATH = Path(__file__).resolve().parents[1] / "app" / "hyperliquid_adapter.py"


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


def test_adapter_does_not_import_duplicate_infra() -> None:
    tree = ast.parse(ADAPTER_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            if node.module.startswith("app."):
                imported.add(node.module.split(".", 1)[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
    assert "app.quantization" not in imported
    assert "app.state_store" not in imported
    assert "app.reconciliation" not in imported
    assert "app.instrument_meta" not in imported
    assert "quantization" not in imported
    assert "state_store" not in imported
    assert "reconciliation" not in imported
    assert "instrument_meta" not in imported


@pytest.mark.asyncio
async def test_candle_source_rejects_unsupported_interval_without_network() -> None:
    adapter = HyperliquidExecutionAdapter(_cfg())

    with pytest.raises(ValueError, match="unsupported candle interval"):
        await adapter.get_candles("BTC-USD", "2m")


@pytest.mark.asyncio
async def test_candle_source_short_cache_avoids_repeated_upstream_requests(monkeypatch) -> None:
    calls = 0

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps([{"t": 1, "o": "100", "h": "101", "l": "99", "c": "100", "v": "1"}]).encode()

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        assert request.full_url == "https://api.hyperliquid-testnet.xyz/info"
        assert timeout == 10
        return Response()

    monkeypatch.setattr("app.hyperliquid_adapter.urlopen", fake_urlopen)
    adapter = HyperliquidExecutionAdapter(_cfg())
    first = await adapter.get_candles("BTC-USD", "5m", 200)
    second = await adapter.get_candles("BTC-USD", "5m", 200)

    assert first == second
    assert calls == 1


@pytest.mark.asyncio
async def test_candle_source_retries_transient_upstream_error(monkeypatch) -> None:
    from urllib.error import HTTPError

    calls = 0

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps([{"t": 1, "o": "100", "h": "101", "l": "99", "c": "100", "v": "1"}]).encode()

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HTTPError(request.full_url, 502, "temporary", {}, None)
        return Response()

    monkeypatch.setattr("app.hyperliquid_adapter.urlopen", fake_urlopen)
    adapter = HyperliquidExecutionAdapter(_cfg())
    candles = await adapter.get_candles("BTC-USD", "5m", 200)

    assert len(candles) == 1
    assert calls == 2


@pytest.mark.asyncio
async def test_candle_source_uses_explicit_mainnet_domain(monkeypatch) -> None:
    seen = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps([{"t": 1, "o": "100", "h": "101", "l": "99", "c": "100", "v": "1"}]).encode()

    def fake_urlopen(request, timeout):
        seen.append(request.full_url)
        return Response()

    monkeypatch.setattr("app.hyperliquid_adapter.urlopen", fake_urlopen)
    adapter = HyperliquidExecutionAdapter(
        _cfg(hyperliquid_domain="hyperliquid_perpetual")
    )
    await adapter.get_candles("BTC-USD", "5m", 3)
    assert seen == ["https://api.hyperliquid.xyz/info"]


@pytest.mark.asyncio
async def test_adapter_has_no_exchange_state_store() -> None:
    adapter = HyperliquidExecutionAdapter(_cfg(), FakeConnector())
    await adapter.connect()
    assert not hasattr(adapter, "store")


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
    assert connector.wire_orders[0]["cloid"] == "0x" + "b" * 32
    second = await adapter.place_order(_req())
    assert connector.place_calls == 1
    assert "not resubmitted" in (second.error or "") or second.status == OrderStatus.FILLED


@pytest.mark.asyncio
async def test_runtime_armed_lifecycle_configure_open_and_cancel() -> None:
    connector = FakeConnector()
    config = _cfg(execution_enabled=True)
    runtime = WorkerRuntime(HyperliquidExecutionAdapter(config, connector), config)
    await runtime.connect()
    runtime.heartbeat()
    await runtime.set_leverage("BTC-USD", 3)
    opened = await runtime.place_order(_req(order_type=OrderType.LIMIT, price=Decimal("100")))
    assert opened.status == OrderStatus.FILLED
    assert connector.wire_orders[0]["cloid"] == _req(order_type=OrderType.LIMIT, price=Decimal("100")).cloid
    canceled = await runtime.cancel_order(opened.cloid, "cancel-1")
    assert canceled is not None
    assert canceled.status == OrderStatus.CANCELED
    assert connector.cancel_calls == 1


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
async def test_reduce_only_close_allows_position_below_entry_notional() -> None:
    connector = FakeConnector()
    adapter = HyperliquidExecutionAdapter(_cfg(execution_enabled=True), connector)
    await adapter.connect()
    result = await adapter.place_order(
        _req(side=OrderSide.SELL, quantity=Decimal("0.001"), reduce_only=True, command="close_position")
    )
    assert result.status == OrderStatus.FILLED
    assert connector.place_calls == 1


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
    pos = await adapter.get_position("ETH-USD")
    assert pos.size == Decimal("1")


@pytest.mark.asyncio
async def test_connector_is_only_position_truth() -> None:
    connector = FakeConnector()
    connector.asset_positions = [
        {
            "type": "oneWay",
            "position": {
                "coin": "BTC",
                "szi": "1",
                "entryPx": "100",
                "unrealizedPnl": "0",
                "leverage": {"value": "1"},
            },
        }
    ]
    adapter = HyperliquidExecutionAdapter(_cfg(), connector)
    await adapter.connect()
    pos = await adapter.get_position("BTC-USD")
    assert pos.side.value == "LONG"
    connector.asset_positions = []
    pos = await adapter.get_position("BTC-USD")
    assert pos.side.value == "FLAT"
    assert adapter.worker_state().value == "READY"


@pytest.mark.asyncio
async def test_unauthenticated_readonly_does_not_claim_flat() -> None:
    connector = FakeConnector()
    connector.read_only = True
    connector.authenticated = False
    adapter = HyperliquidExecutionAdapter(_cfg(), connector)
    await adapter.connect()
    assert adapter.worker_state().value == "RECOVERING"
    with pytest.raises(LookupError, match="authenticated account read"):
        await adapter.get_position("BTC-USD")


@pytest.mark.asyncio
async def test_failed_account_read_does_not_claim_flat() -> None:
    connector = FakeConnector()
    connector.account_read = "position_query_failed"
    adapter = HyperliquidExecutionAdapter(_cfg(), connector)
    await adapter.connect()
    assert adapter.worker_state().value == "RECOVERING"
    with pytest.raises(LookupError, match="authenticated account read"):
        await adapter.get_positions()


@pytest.mark.asyncio
async def test_get_balance_raises_when_untrusted() -> None:
    connector = FakeConnector()
    connector.read_only = True
    connector.authenticated = False
    adapter = HyperliquidExecutionAdapter(_cfg(), connector)
    await adapter.connect()
    with pytest.raises(LookupError, match="authenticated account balances"):
        await adapter.get_balance()


@pytest.mark.asyncio
async def test_get_balance_raises_when_account_keys_missing() -> None:
    connector = FakeConnector()
    connector.account = {}
    adapter = HyperliquidExecutionAdapter(_cfg(), connector)
    await adapter.connect()
    with pytest.raises(LookupError, match="authenticated account balances"):
        await adapter.get_balance()


@pytest.mark.asyncio
async def test_get_balance_uses_connector_account_and_not_default_zero() -> None:
    connector = FakeConnector()
    connector.account = {"equity": "19.4", "available": "18.1", "margin_used": "1.3"}
    adapter = HyperliquidExecutionAdapter(_cfg(), connector)
    await adapter.connect()
    bal = await adapter.get_balance()
    assert bal.equity == Decimal("19.4")
    assert bal.available == Decimal("18.1")
    assert bal.margin_used == Decimal("1.3")


@pytest.mark.asyncio
async def test_market_data_refreshes_transient_zero_mid() -> None:
    class _PriceReadyAfterFirstSnapshot(FakeConnector):
        def __init__(self) -> None:
            super().__init__()
            self._snapshots = 0

        async def rest_snapshot(self) -> dict:
            self._snapshots += 1
            snapshot = await super().rest_snapshot()
            if self._snapshots == 1:
                snapshot["mid"] = "0"
            else:
                snapshot["mid"] = "100"
            return snapshot

    connector = _PriceReadyAfterFirstSnapshot()
    adapter = HyperliquidExecutionAdapter(_cfg(), connector)
    await adapter.connect()
    market = await adapter.get_market_data("BTC-USD")
    assert market["mid"] == Decimal("100")
    assert connector._snapshots == 2


@pytest.mark.asyncio
async def test_armed_bridge_adapter_places_injected_cloid_and_still_blocks_cancel() -> None:
    from app.hummingbot_readonly import ReadOnlyHummingbotBridge

    class _Stub:
        def __init__(self) -> None:
            self.recorded: list[str] = []
            self.account_positions = {}
            self.in_flight_orders = {}
            self.trading_rules = {
                "BTC-USD": type("R", (), {
                    "min_base_amount_increment": Decimal("0.00001"),
                    "min_price_increment": Decimal("0.1"),
                    "min_order_size": Decimal("0.00001"),
                    "min_notional_size": Decimal("10"),
                })()
            }
            self._trading_pairs = ["BTC-USD"]

        async def start_network(self) -> None:
            return None

        def add_listener(self, event, cb) -> None:
            _ = event, cb

        def quantize_order_price(self, trading_pair: str, price: Decimal) -> Decimal:
            _ = trading_pair
            return price

        def quantize_order_amount(self, trading_pair: str, amount: Decimal) -> Decimal:
            _ = trading_pair
            return amount

        def get_price(self, trading_pair: str, is_buy: bool):
            _ = trading_pair, is_buy
            return Decimal("100")

        async def _place_order(self, order_id: str, *args, **kwargs):
            self.recorded.append(str(order_id))
            return {
                "order": {
                    "cloid": order_id,
                    "oid": "7",
                    "status": "filled",
                    "symbol": "BTC-USD",
                    "side": "BUY",
                    "sz": "0",
                    "origSz": "0.2",
                }
            }

        def buy(self, *args, **kwargs):
            raise AssertionError("buy must not run")

        def sell(self, *args, **kwargs):
            raise AssertionError("sell must not run")

    stub = _Stub()
    unarmed = ReadOnlyHummingbotBridge(stub, authenticated=True, execution_enabled=False)
    dry = HyperliquidExecutionAdapter(_cfg(execution_enabled=False), unarmed)
    rejected = await dry.place_order(_req())
    assert rejected.status == OrderStatus.REJECTED
    assert stub.recorded == []

    armed = ReadOnlyHummingbotBridge(stub, authenticated=True, execution_enabled=True)
    live = HyperliquidExecutionAdapter(_cfg(execution_enabled=True), armed)
    first = await live.place_order(_req())
    assert first.status in {OrderStatus.FILLED, OrderStatus.OPEN}
    assert stub.recorded == [_req().cloid]
    with pytest.raises(ExecutionDisabled):
        await live.cancel_order(_req().cloid, "r1")
    with pytest.raises(ExecutionDisabled):
        await live.set_leverage("BTC-USD", 3)
