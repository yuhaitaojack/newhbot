from __future__ import annotations

from decimal import Decimal
from typing import Any


def _trade_type(is_buy: bool):
    try:
        from hummingbot.core.data_type.common import TradeType

        return TradeType.BUY if is_buy else TradeType.SELL
    except Exception:
        return "BUY" if is_buy else "SELL"


def _order_type(tif: str):
    try:
        from hummingbot.core.data_type.common import OrderType

        return OrderType.MARKET if tif == "Ioc" else OrderType.LIMIT
    except Exception:
        return "MARKET" if tif == "Ioc" else "LIMIT"


def _position_action(reduce_only: bool):
    try:
        from hummingbot.core.data_type.common import PositionAction

        return PositionAction.CLOSE if reduce_only else PositionAction.OPEN
    except Exception:
        return "CLOSE" if reduce_only else "OPEN"


async def place_with_injected_cloid(connector: Any, wire: dict) -> dict:
    """Submit one order using the business cloid. Never call buy()/sell().

    Hummingbot v2.16.0 facts (source + STEP 2.5 stub runtime):

    - buy()/sell() mint a second MD5 cloid. Forbidden.
    - _place_order puts \"cloid\": order_id on the signed payload as-is.
    - No inner retry / renew / second place.

    Production Adapter only reaches this when EXECUTION_ENABLED is true.
    Default remains false. Never call this through ReadOnlyGuard; the armed
    Bridge uses a shim that exposes only saved internal execution seams.
    """
    from app.readonly_guard import ReadOnlyGuard, ReadOnlyViolation

    if isinstance(connector, ReadOnlyGuard):
        raise ReadOnlyViolation("place_with_injected_cloid must not be called through ReadOnlyGuard")
    cloid = str(wire["cloid"])
    if not cloid.startswith("0x"):
        raise ValueError("business cloid is required")
    _ = getattr(connector, "buy", None), getattr(connector, "sell", None)
    is_buy = bool(wire["is_buy"])
    reduce_only = bool(wire.get("reduce_only"))
    tif = wire.get("tif", "Ioc")
    trading_pair = str(wire["symbol"])
    amount = Decimal(str(wire["sz"]))
    order_type = _order_type(tif)
    trade_type = _trade_type(is_buy)
    position_action = _position_action(reduce_only)
    start_tracking = getattr(connector, "start_tracking_order", None)
    if callable(start_tracking):
        existing = getattr(connector, "in_flight_orders", None) or {}
        known = existing.get(cloid) if hasattr(existing, "get") else None
        if known is None:
            start_tracking(
                order_id=cloid,
                exchange_order_id=None,
                trading_pair=trading_pair,
                trade_type=trade_type,
                price=Decimal(str(wire["limit_px"])),
                amount=amount,
                order_type=order_type,
                position_action=position_action,
            )
    try:
        result = await connector._place_order(
            order_id=cloid,
            trading_pair=trading_pair,
            amount=amount,
            trade_type=trade_type,
            order_type=order_type,
            price=Decimal(str(wire["limit_px"])),
            position_action=position_action,
        )
    except Exception as exc:
        record_failure = getattr(connector, "record_failure", None)
        if callable(record_failure):
            record_failure(cloid, trading_pair, exc)
        raise
    if isinstance(result, dict):
        order = result.get("order") or {}
        oid = order.get("oid")
        timestamp = result.get("timestamp")
        if oid is not None:
            record_submission = getattr(connector, "record_submission", None)
            if callable(record_submission):
                record_submission(cloid, str(oid), timestamp)
        return result
    oid, timestamp = result
    record_submission = getattr(connector, "record_submission", None)
    if callable(record_submission):
        record_submission(cloid, str(oid), timestamp)
    return {"order": {"cloid": cloid, "oid": str(oid), "status": "open"}, "timestamp": timestamp}
