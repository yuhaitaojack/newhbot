from __future__ import annotations

from decimal import Decimal

from app.exchange_models import ExchangeOrder, ExchangePosition
from app.mapping import map_hummingbot_position
from app.protocol import OrderSide, OrderStatus, OrderType, PositionSide
from app.state_store import ExchangeStateStore


def test_legacy_store_helper_keeps_conflict_without_overwrite() -> None:
    """Characterization of unused helper. Production Adapter does not use this store."""
    store = ExchangeStateStore()
    store.apply_rest_snapshot(
        positions=[
            map_hummingbot_position(
                {"coin": "BTC", "szi": "1", "entryPx": "100", "unrealizedPnl": "0", "leverage": {"value": "1"}},
                configured_pair="BTC-USD",
            )
        ],
        orders=[],
    )
    store.apply_ws_position(
        map_hummingbot_position(
            {"coin": "BTC", "szi": "-1", "entryPx": "100", "unrealizedPnl": "0", "leverage": {"value": "1"}},
            configured_pair="BTC-USD",
        )
    )
    assert store.needs_reconciliation is True
    assert store.positions["BTC-USD"].side == PositionSide.LONG


def test_legacy_store_helper_resync_after_ws_drop() -> None:
    store = ExchangeStateStore()
    store.apply_rest_snapshot(
        positions=[ExchangePosition(symbol="BTC-USD", side=PositionSide.FLAT, size=Decimal("0"))],
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
            status=OrderStatus.OPEN,
        )
    )
    store.mark_ws(False)
    store.resync_from_rest(
        positions=[
            map_hummingbot_position(
                {"coin": "BTC", "szi": "1", "entryPx": "100", "unrealizedPnl": "0", "leverage": {"value": "1"}},
                configured_pair="BTC-USD",
            )
        ],
        orders=[],
    )
    assert store.positions["BTC-USD"].side == PositionSide.LONG
    assert store.needs_reconciliation is False
