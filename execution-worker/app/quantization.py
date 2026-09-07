"""Characterization of Hummingbot v2.16.0 Hyperliquid quantize formulas.

Production HyperliquidExecutionAdapter does not import this module. FakeConnector
uses it as the stand-in for Connector.quantize_order_price / amount. Live
production must call Hummingbot Connector quantize methods.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from app.config import MIN_NOTIONAL_SIZE
from app.exchange_models import InstrumentMeta
from app.protocol import PlaceOrderRequest


class QuantizeReject(ValueError):
    """Quantity/price cannot be submitted. Never silently bump size."""


def five_significant_figures(price: Decimal) -> Decimal:
    """Decimal stand-in for v2.16.0 `float(f"{price:.5g}")` before tick rounding."""
    if price == 0:
        return Decimal("0")
    adjusted = price.adjusted()
    quantum = Decimal("1e{0}".format(adjusted - 4))
    return price.quantize(quantum, rounding=ROUND_HALF_UP)


def quantize_order_price(price: Decimal, tick: Decimal) -> Decimal:
    """Match Hummingbot v2.16.0 HyperliquidPerpetualDerivative.quantize_order_price.

    1. At most 5 significant figures.
    2. Align to min_price_increment with ROUND_HALF_UP.
    3. Strip padded zeros without scientific notation.
    """
    if tick <= 0:
        raise QuantizeReject("tick size must be positive")
    price = five_significant_figures(price)
    quantized = (price / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick
    quantized = quantized.normalize()
    if quantized.as_tuple().exponent > 0:
        quantized = quantized.quantize(Decimal("1"))
    if quantized <= 0:
        raise QuantizeReject("quantized price must be positive")
    return quantized


def quantize_order_size(quantity: Decimal, step: Decimal) -> Decimal:
    """Round DOWN to szDecimals step. Never round up into a larger order."""
    if step <= 0:
        raise QuantizeReject("step size must be positive")
    if quantity <= 0:
        raise QuantizeReject("quantity must be positive")
    steps = (quantity / step).to_integral_value(rounding=ROUND_DOWN)
    return steps * step


def normalize_order_request(request: PlaceOrderRequest, meta: InstrumentMeta, price: Decimal) -> PlaceOrderRequest:
    qty = quantize_order_size(request.quantity, meta.step_size)
    if qty <= 0:
        raise QuantizeReject("quantity quantized to zero")
    if qty < meta.min_order_size:
        raise QuantizeReject("quantity below exchange minimum")
    px = quantize_order_price(price, meta.tick_size)
    notional = qty * px
    min_notional = meta.min_notional if meta.min_notional > 0 else MIN_NOTIONAL_SIZE
    # A reduce-only order may be smaller than the normal entry minimum. This
    # is required to close a partially filled position whose remaining
    # notional has fallen below the exchange's entry threshold.
    if not request.reduce_only and notional < min_notional:
        raise QuantizeReject(f"notional {notional} below minimum {min_notional}")
    return request.model_copy(update={"quantity": qty, "price": px})
