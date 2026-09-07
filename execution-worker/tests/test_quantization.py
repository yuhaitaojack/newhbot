from __future__ import annotations

from decimal import Decimal

import pytest

from app.quantization import QuantizeReject, normalize_order_request, quantize_order_price, quantize_order_size
from app.exchange_models import InstrumentMeta
from app.protocol import OrderSide, OrderType, PlaceOrderRequest


def _meta(**kwargs) -> InstrumentMeta:
    data = dict(
        symbol="BTC-USD",
        sz_decimals=4,
        step_size=Decimal("0.0001"),
        tick_size=Decimal("0.01"),
        min_order_size=Decimal("0.0001"),
        min_notional=Decimal("10"),
        max_leverage=50,
    )
    data.update(kwargs)
    return InstrumentMeta(**data)


def test_quantize_price_five_sigfigs_and_tick() -> None:
    assert quantize_order_price(Decimal("100.126"), Decimal("0.01")) == Decimal("100.13")
    assert quantize_order_price(Decimal("0.094605"), Decimal("0.00001")) == Decimal("0.09461")


def test_quantize_size_rounds_down_never_up() -> None:
    assert quantize_order_size(Decimal("1.23456"), Decimal("0.0001")) == Decimal("1.2345")
    with pytest.raises(QuantizeReject):
        quantize_order_size(Decimal("0"), Decimal("0.0001"))


def test_normalize_rejects_below_min_and_notional() -> None:
    meta = _meta()
    tiny = PlaceOrderRequest(
        request_id="r",
        cloid="0x" + "1" * 32,
        symbol="BTC-USD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.00001"),
    )
    with pytest.raises(QuantizeReject, match="zero|minimum"):
        normalize_order_request(tiny, meta, Decimal("100"))
    small_notional = PlaceOrderRequest(
        request_id="r2",
        cloid="0x" + "2" * 32,
        symbol="BTC-USD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.001"),
    )
    with pytest.raises(QuantizeReject, match="notional"):
        normalize_order_request(small_notional, meta, Decimal("100"))
    ok = PlaceOrderRequest(
        request_id="r3",
        cloid="0x" + "3" * 32,
        symbol="BTC-USD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.2"),
    )
    out = normalize_order_request(ok, meta, Decimal("100"))
    assert out.quantity == Decimal("0.2")
    assert out.price == Decimal("100.00") or out.price == Decimal("100")


def test_reduce_only_allows_below_entry_minimum() -> None:
    request = PlaceOrderRequest(
        request_id="close-r",
        cloid="0x" + "4" * 32,
        symbol="BTC-USD",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.001"),
        reduce_only=True,
    )
    out = normalize_order_request(request, _meta(), Decimal("100"))
    assert out.quantity == Decimal("0.001")
