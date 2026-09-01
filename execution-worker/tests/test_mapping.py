from __future__ import annotations

from decimal import Decimal

import pytest

from app.mapping import OneWayError, map_clearinghouse_positions, map_hummingbot_fill, map_hummingbot_order
from app.protocol import OrderStatus, PositionSide


def test_map_position_long_short_flat() -> None:
    long_pos, _ = map_clearinghouse_positions(
        [{"type": "oneWay", "position": {"coin": "BTC", "szi": "0.5", "entryPx": "100", "unrealizedPnl": "1", "leverage": {"value": "3"}}}],
        configured_pair="BTC-USD",
    )
    assert long_pos[0].side == PositionSide.LONG
    assert long_pos[0].size == Decimal("0.5")
    short_pos, _ = map_clearinghouse_positions(
        [{"type": "oneWay", "position": {"coin": "BTC", "szi": "-0.2", "entryPx": "100", "unrealizedPnl": "0", "leverage": {"value": "1"}}}],
        configured_pair="BTC-USD",
    )
    assert short_pos[0].side == PositionSide.SHORT
    empty, _ = map_clearinghouse_positions([], configured_pair="BTC-USD")
    assert empty == []


def test_hedge_dual_position_is_illegal() -> None:
    with pytest.raises(OneWayError):
        map_clearinghouse_positions(
            [
                {"type": "oneWay", "position": {"coin": "BTC", "szi": "1", "entryPx": "100", "unrealizedPnl": "0", "leverage": {"value": "1"}}},
                {"type": "oneWay", "position": {"coin": "BTC", "szi": "-1", "entryPx": "100", "unrealizedPnl": "0", "leverage": {"value": "1"}}},
            ],
            configured_pair="BTC-USD",
        )


def test_map_order_and_fill_from_hummingbot_shaped_payloads() -> None:
    order = map_hummingbot_order(
        {
            "status": "open",
            "order": {
                "oid": 9,
                "cloid": "0x" + "a" * 32,
                "coin": "BTC",
                "side": "B",
                "sz": "0.1",
                "origSz": "0.2",
                "limitPx": "101",
                "reduceOnly": False,
                "timestamp": 1_700_000_000_000,
            },
        }
    )
    assert order.status == OrderStatus.OPEN
    assert order.filled_quantity == Decimal("0.1")
    fill = map_hummingbot_fill(
        {"tid": 1, "oid": 9, "cloid": order.cloid, "coin": "BTC", "side": "B", "px": "101", "sz": "0.1", "fee": "0.01", "time": 1_700_000_000_000}
    )
    assert fill.quantity == Decimal("0.1")
    assert fill.fee == Decimal("0.01")
    assert fill.symbol == "BTC-USD"
    assert order.cloid.startswith("0x")
    assert len(order.cloid) == 34
