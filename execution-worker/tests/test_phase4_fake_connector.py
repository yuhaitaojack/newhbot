"""FAKE CONNECTOR tests for PHASE 4 read-only reconciliation.

These tests never import Hummingbot and never contact a trading account.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import WorkerConfig
from app.connector_bridge import FakeConnector
from app.exchange_models import ExchangeFill, ExchangePosition, InstrumentMeta
from app.hyperliquid_adapter import ExecutionDisabled, HyperliquidExecutionAdapter
from app.instrument_meta import default_btc_instrument_meta, extract_coin_meta
from app.mapping import map_clearinghouse_positions, map_hummingbot_fill, map_hummingbot_order
from app.protocol import OrderSide, OrderStatus, OrderType, PlaceOrderRequest, PositionSide
from app.quantization import normalize_order_request, quantize_order_size
from app.readonly_guard import ReadOnlyGuard, ReadOnlyViolation
from app.reconciliation import compare_rest_and_hummingbot
from app.runtime import WorkerRuntime
from app.state_store import ExchangeStateStore
from app.factory import build_runtime

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "btc_meta_snapshot.json"
PHASE3_PLACEHOLDER = InstrumentMeta(
    symbol="BTC-USD",
    sz_decimals=4,
    step_size=Decimal("0.0001"),
    tick_size=Decimal("0.01"),
    min_order_size=Decimal("0.0001"),
    min_notional=Decimal("10"),
    max_leverage=50,
)


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


def _pos(coin: str, szi: str) -> dict:
    return {
        "type": "oneWay",
        "position": {
            "coin": coin,
            "szi": szi,
            "entryPx": "100",
            "unrealizedPnl": "0",
            "leverage": {"value": "1"},
        },
    }


# --- 3. read-only safety (FAKE CONNECTOR) ---


def test_fake_readonly_guard_blocks_trading_methods() -> None:
    connector = FakeConnector()
    guard = ReadOnlyGuard(connector)
    with pytest.raises(ReadOnlyViolation):
        guard.buy("BTC-USD", Decimal("1"))
    with pytest.raises(ReadOnlyViolation):
        guard.sell("BTC-USD", Decimal("1"))
    with pytest.raises(ReadOnlyViolation):
        guard._place_order()
    with pytest.raises(ReadOnlyViolation):
        guard.cancel("0x" + "a" * 32)
    with pytest.raises(ReadOnlyViolation):
        guard.set_leverage("BTC-USD", 2)
    assert guard.violations == ["buy", "sell", "_place_order", "cancel", "set_leverage"]


# --- 4. position mapping ---


def test_fake_position_mapping_szi() -> None:
    long_pos, _ = map_clearinghouse_positions([_pos("BTC", "0.5")], configured_pair="BTC-USD")
    assert long_pos[0].side == PositionSide.LONG
    assert long_pos[0].symbol == "BTC-USD"
    short_pos, _ = map_clearinghouse_positions([_pos("BTC", "-0.2")], configured_pair="BTC-USD")
    assert short_pos[0].side == PositionSide.SHORT
    gone, _ = map_clearinghouse_positions([], configured_pair="BTC-USD")
    assert gone == []


# --- 5. order mapping / cloid format from v2.16.0 source ---


def test_fake_order_mapping_cloid_is_0x_md5_hex() -> None:
    cloid = "0x" + "ab" * 16
    order = map_hummingbot_order(
        {
            "status": "open",
            "order": {
                "oid": 9,
                "cloid": cloid,
                "coin": "BTC",
                "side": "B",
                "sz": "0.1",
                "origSz": "0.2",
                "limitPx": "101",
                "reduceOnly": False,
                "orderType": {"limit": {"tif": "Gtc"}},
                "timestamp": 1_700_000_000_000,
            },
        },
        configured_pair="BTC-USD",
    )
    assert order.cloid == cloid
    assert len(order.cloid) == 34
    assert order.cloid.startswith("0x")
    assert order.exchange_order_id == "9"
    assert order.symbol == "BTC-USD"
    assert order.side == OrderSide.BUY
    assert order.reduce_only is False
    assert order.status == OrderStatus.OPEN
    empty = map_hummingbot_order({"status": "open", "order": {"oid": 1, "coin": "BTC", "side": "A", "sz": "1"}}, configured_pair="BTC-USD")
    assert empty.cloid == ""


# --- 6. fill mapping ---


def test_fake_fill_mapping() -> None:
    fill = map_hummingbot_fill(
        {
            "tid": 77,
            "oid": 9,
            "cloid": "0x" + "ab" * 16,
            "coin": "BTC",
            "side": "B",
            "px": "101",
            "sz": "0.1",
            "fee": "0.01",
            "time": 1_700_000_000_000,
        },
        configured_pair="BTC-USD",
    )
    assert fill.fill_id == "77"
    assert fill.order_id == "9"
    assert fill.symbol == "BTC-USD"
    assert fill.side == OrderSide.BUY
    assert fill.fee == Decimal("0.01")


# --- 7. instrument metadata vs PHASE 3 placeholder ---


def test_fake_instrument_metadata_mismatch_then_fixed_default() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    live = extract_coin_meta([{"universe": raw["universe"]}, raw["ctxs"]], "BTC")
    assert live.sz_decimals != PHASE3_PLACEHOLDER.sz_decimals
    assert live.tick_size != PHASE3_PLACEHOLDER.tick_size
    assert live.step_size != PHASE3_PLACEHOLDER.step_size
    # MISMATCH recorded: PHASE 3 placeholder szDecimals=4 / tick=0.01.
    # Product default now follows the v2.16.0 public snapshot.
    fixed = default_btc_instrument_meta()
    assert fixed.sz_decimals == live.sz_decimals == 5
    assert fixed.tick_size == live.tick_size == Decimal("0.1")
    assert fixed.min_order_size == live.min_order_size == Decimal("0.00001")
    assert fixed.min_notional == Decimal("10")
    qty = quantize_order_size(Decimal("0.000019"), live.step_size)
    assert qty == Decimal("0.00001")
    req = PlaceOrderRequest(
        request_id="r",
        cloid="0x" + "3" * 32,
        symbol="BTC-USD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.2"),
    )
    out = normalize_order_request(req, live, Decimal("78002.0"))
    assert out.quantity == Decimal("0.2")
    assert out.price == Decimal("78002.0")


# --- 8. foreign position ---


@pytest.mark.asyncio
async def test_fake_foreign_position_recovering_no_autoclose() -> None:
    connector = FakeConnector()
    connector.asset_positions = [_pos("ETH", "1")]
    adapter = HyperliquidExecutionAdapter(_cfg(), connector)
    await adapter.connect()
    assert adapter.foreign_symbols == ["ETH-USD"]
    assert adapter.worker_state().value == "RECOVERING"
    assert connector.cancel_calls == 0
    assert connector.place_calls == 0


# --- 9. REST / Hummingbot disagreement is CONFLICT, not silent REST overwrite ---


@pytest.mark.asyncio
async def test_fake_rest_hummingbot_conflict_forbids_ready() -> None:
    connector = FakeConnector()
    connector.asset_positions = [_pos("BTC", "1")]
    connector.hummingbot_account_positions = [_pos("BTC", "-1")]
    adapter = HyperliquidExecutionAdapter(_cfg(), connector)
    await adapter.connect()
    assert adapter.store.needs_reconciliation is True
    assert "disagree" in (adapter.store.conflict_reason or "")
    assert adapter.worker_state().value == "RECOVERING"
    runtime = WorkerRuntime(adapter, _cfg())
    rejected = await runtime.place_order(_req())
    assert rejected.status == OrderStatus.REJECTED
    assert "RECOVERING" in (rejected.error or "")


@pytest.mark.asyncio
async def test_fake_rest_hummingbot_agree_then_ready() -> None:
    connector = FakeConnector()
    connector.asset_positions = [_pos("BTC", "1")]
    adapter = HyperliquidExecutionAdapter(_cfg(), connector)
    await adapter.connect()
    assert adapter.store.needs_reconciliation is False
    assert adapter.worker_state().value == "READY"


# --- 10. WS disconnect recovery ---


@pytest.mark.asyncio
async def test_fake_ws_disconnect_degraded_then_resync_ready() -> None:
    connector = FakeConnector()
    adapter = HyperliquidExecutionAdapter(_cfg(), connector)
    await adapter.connect()
    runtime = WorkerRuntime(adapter, _cfg())
    assert runtime.ready is True
    runtime.mark_ws_down()
    assert runtime.state.value == "DEGRADED"
    rejected = await runtime.place_order(_req())
    assert rejected.status == OrderStatus.REJECTED
    await runtime.rest_resync()
    assert runtime.ready is True


# --- 11. duplicate fill ---


def test_fake_duplicate_fill_not_replayed() -> None:
    store = ExchangeStateStore()
    fill = ExchangeFill(
        fill_id="77",
        order_id="9",
        cloid="0x" + "ab" * 16,
        symbol="BTC-USD",
        side=OrderSide.BUY,
        price=Decimal("101"),
        quantity=Decimal("0.1"),
    )
    store.apply_ws_fill(fill)
    store.apply_ws_fill(fill)
    assert len(store.fills) == 1


# --- 12. stale BTC when REST omits it ---


@pytest.mark.asyncio
async def test_fake_stale_btc_dropped_when_rest_omits_it() -> None:
    connector = FakeConnector()
    connector.asset_positions = [_pos("BTC", "1"), _pos("ETH", "2")]
    adapter = HyperliquidExecutionAdapter(_cfg(), connector)
    await adapter.connect()
    assert "BTC-USD" in adapter.store.positions
    connector.asset_positions = [_pos("ETH", "2")]
    await adapter._rest_snapshot()
    assert "BTC-USD" not in adapter.store.positions
    assert "ETH-USD" in adapter.store.positions
    assert adapter.foreign_symbols == ["ETH-USD"]
    assert adapter.worker_state().value == "RECOVERING"


@pytest.mark.asyncio
async def test_fake_btc_flat_eth_absent_ready() -> None:
    connector = FakeConnector()
    connector.asset_positions = [_pos("BTC", "1")]
    adapter = HyperliquidExecutionAdapter(_cfg(), connector)
    await adapter.connect()
    connector.asset_positions = []
    await adapter._rest_snapshot()
    adapter.store.mark_ws(True)
    assert adapter.store.positions == {}
    assert adapter.foreign_symbols == []
    assert adapter.worker_state().value == "READY"


# --- 13. one-way ---


def test_fake_one_way_does_not_require_hedge() -> None:
    rest, _ = map_clearinghouse_positions([_pos("BTC", "1")], configured_pair="BTC-USD")
    hb, _ = map_clearinghouse_positions([_pos("BTC", "1")], configured_pair="BTC-USD")
    assert compare_rest_and_hummingbot(rest, hb) is None
    assert all(item.side in {PositionSide.LONG, PositionSide.SHORT} for item in rest)


# --- 14. Worker READY gate ---


@pytest.mark.asyncio
async def test_fake_worker_ready_gate() -> None:
    runtime = WorkerRuntime(HyperliquidExecutionAdapter(_cfg(), FakeConnector()), _cfg())
    not_ready = await runtime.place_order(_req())
    assert not_ready.status == OrderStatus.REJECTED
    await runtime.connect()
    assert runtime.ready is True


@pytest.mark.asyncio
async def test_fake_readonly_adapter_never_places() -> None:
    connector = FakeConnector()
    connector.read_only = True
    adapter = HyperliquidExecutionAdapter(_cfg(execution_enabled=True), connector)
    await adapter.connect()
    result = await adapter.place_order(_req())
    assert result.status == OrderStatus.REJECTED
    assert connector.place_calls == 0
    with pytest.raises(ExecutionDisabled):
        await adapter.set_leverage("BTC-USD", 5)
    with pytest.raises(ExecutionDisabled):
        await adapter.cancel_order("0x" + "b" * 32, "r1")


def test_live_connector_without_package_raises() -> None:
    from app.hummingbot_readonly import try_load_hummingbot_connector_class

    if try_load_hummingbot_connector_class() is not None:
        pytest.skip("REAL CONNECTOR is importable here; see test_phase4_real_connector.py")
    with pytest.raises(RuntimeError, match="not importable"):
        build_runtime(_cfg(use_live_connector=True))


def test_live_connector_rejects_execution_enabled() -> None:
    with pytest.raises(RuntimeError, match="EXECUTION_ENABLED"):
        build_runtime(_cfg(use_live_connector=True, execution_enabled=True))
