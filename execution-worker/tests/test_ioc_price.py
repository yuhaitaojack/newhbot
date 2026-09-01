from __future__ import annotations

from decimal import Decimal

import pytest

from app.ioc_price import close_side_for_position, ioc_limit_price
from app.protocol import OrderSide


def test_long_close_sell_price_below_mid() -> None:
    mid = Decimal("100")
    tick = Decimal("0.01")
    px = ioc_limit_price(side=OrderSide.SELL, mid=mid, slippage=Decimal("0.05"), tick=tick)
    assert px < mid
    assert px == Decimal("95.00") or px == Decimal("95")
    assert close_side_for_position("LONG") == OrderSide.SELL


def test_short_close_buy_price_above_mid() -> None:
    mid = Decimal("100")
    tick = Decimal("0.01")
    px = ioc_limit_price(side=OrderSide.BUY, mid=mid, slippage=Decimal("0.05"), tick=tick)
    assert px > mid
    assert px == Decimal("105.00") or px == Decimal("105")
    assert close_side_for_position("SHORT") == OrderSide.BUY


def test_extreme_slippage_keeps_direction() -> None:
    mid = Decimal("100")
    tick = Decimal("0.01")
    sell = ioc_limit_price(side=OrderSide.SELL, mid=mid, slippage=Decimal("0.9"), tick=tick)
    buy = ioc_limit_price(side=OrderSide.BUY, mid=mid, slippage=Decimal("0.9"), tick=tick)
    assert sell < mid < buy
    with pytest.raises(ValueError):
        ioc_limit_price(side=OrderSide.SELL, mid=mid, slippage=Decimal("1.5"), tick=tick)
    with pytest.raises(ValueError):
        close_side_for_position("FLAT")
