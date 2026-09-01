from __future__ import annotations

from decimal import Decimal

from app.protocol import OrderSide
from app.quantization import quantize_order_price


def ioc_limit_price(*, side: OrderSide, mid: Decimal, slippage: Decimal, tick: Decimal) -> Decimal:
    """IOC protective limit used as Hyperliquid 'market' (connector v2.16.0).

    BUY (open long or close short): mid * (1 + slippage) — must not be below market.
    SELL (open short or close long): mid * (1 - slippage) — must not be above market.
    """
    if mid <= 0:
        raise ValueError("mid price must be positive")
    if slippage < 0:
        raise ValueError("slippage must be >= 0")
    if side == OrderSide.BUY:
        raw = mid * (Decimal("1") + slippage)
    else:
        raw = mid * (Decimal("1") - slippage)
    if raw <= 0:
        raise ValueError("IOC price collapsed to non-positive; slippage too large")
    return quantize_order_price(raw, tick)


def close_side_for_position(position_side: str) -> OrderSide:
    if position_side == "LONG":
        return OrderSide.SELL
    if position_side == "SHORT":
        return OrderSide.BUY
    raise ValueError("FLAT has no close side")
