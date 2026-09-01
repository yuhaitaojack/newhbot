from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.exchange_models import ExchangeFill, ExchangeOrder, ExchangePosition
from app.protocol import OrderSide, OrderStatus, OrderType, PositionSide

HB_ORDER_STATE = {
    "open": OrderStatus.OPEN,
    "resting": OrderStatus.OPEN,
    "filled": OrderStatus.FILLED,
    "canceled": OrderStatus.CANCELED,
    "rejected": OrderStatus.REJECTED,
    "badAloPxRejected": OrderStatus.REJECTED,
    "minTradeNtlRejected": OrderStatus.REJECTED,
    "reduceOnlyCanceled": OrderStatus.CANCELED,
    "reduceOnlyRejected": OrderStatus.REJECTED,
    "perpMarginRejected": OrderStatus.REJECTED,
    "selfTradeCanceled": OrderStatus.CANCELED,
    "siblingFilledCanceled": OrderStatus.CANCELED,
    "delistedCanceled": OrderStatus.CANCELED,
    "liquidatedCanceled": OrderStatus.CANCELED,
}


class OneWayError(ValueError):
    """Account cannot be mapped to a single FLAT/LONG/SHORT."""


def to_pair_symbol(coin: str, *, configured_pair: str) -> str:
    symbol = str(coin)
    if not symbol:
        return symbol
    if "-" in symbol:
        return symbol
    if configured_pair.endswith("-USD"):
        return f"{symbol}-USD"
    return symbol


def map_szi_to_side(szi: Decimal) -> PositionSide:
    if szi > 0:
        return PositionSide.LONG
    if szi < 0:
        return PositionSide.SHORT
    return PositionSide.FLAT


def map_hummingbot_position(raw: dict, *, configured_pair: str) -> ExchangePosition:
    """Map v2.16.0 `_update_positions` fields. szi>0 LONG, szi<0 SHORT."""
    coin = raw.get("coin") or raw.get("symbol")
    szi = Decimal(str(raw.get("szi", "0")))
    side = map_szi_to_side(szi)
    leverage_raw = raw.get("leverage")
    leverage = None
    if isinstance(leverage_raw, dict):
        leverage = int(Decimal(str(leverage_raw.get("value", "0"))))
    elif leverage_raw is not None:
        leverage = int(Decimal(str(leverage_raw)))
    ts = raw.get("timestamp")
    timestamp = datetime.fromtimestamp(ts / 1000, tz=timezone.utc) if isinstance(ts, (int, float)) else datetime.now(timezone.utc)
    symbol = to_pair_symbol(str(coin), configured_pair=configured_pair)
    return ExchangePosition(
        symbol=symbol,
        side=side,
        size=abs(szi),
        entry_price=Decimal(str(raw["entryPx"])) if raw.get("entryPx") not in (None, "") else None,
        mark_price=Decimal(str(raw["markPx"])) if raw.get("markPx") not in (None, "") else None,
        unrealized_pnl=Decimal(str(raw.get("unrealizedPnl", "0"))),
        leverage=leverage,
        timestamp=timestamp,
    )


def map_clearinghouse_positions(asset_positions: list[dict], *, configured_pair: str) -> tuple[list[ExchangePosition], list[str]]:
    """Return mapped positions and illegal-state reasons. Hedge/dual side → OneWayError via reasons."""
    mapped: list[ExchangePosition] = []
    reasons: list[str] = []
    by_symbol: dict[str, list[ExchangePosition]] = {}
    for item in asset_positions:
        pos = item.get("position", item)
        pos_type = item.get("type") or pos.get("type")
        if pos_type and pos_type not in {"oneWay", "oneway", None}:
            reasons.append(f"unsupported position type {pos_type}")
        exchange_pos = map_hummingbot_position(pos, configured_pair=configured_pair)
        if exchange_pos.size == 0 or exchange_pos.side == PositionSide.FLAT:
            continue
        by_symbol.setdefault(exchange_pos.symbol, []).append(exchange_pos)
        mapped.append(exchange_pos)
    for symbol, rows in by_symbol.items():
        sides = {row.side for row in rows}
        if PositionSide.LONG in sides and PositionSide.SHORT in sides:
            reasons.append(f"hedge/dual position on {symbol}")
            raise OneWayError(f"LONG and SHORT both present for {symbol}")
    return mapped, reasons


def map_hummingbot_order(raw: dict, *, configured_pair: str = "BTC-USD") -> ExchangeOrder:
    inner = raw.get("order", raw)
    status_raw = str(raw.get("status") or inner.get("status") or "open")
    qty = Decimal(str(inner.get("sz", inner.get("quantity", "0"))))
    filled = Decimal(str(inner.get("filled_quantity", inner.get("origSz", qty) if inner.get("origSz") else "0")))
    if "origSz" in inner:
        orig = Decimal(str(inner["origSz"]))
        remaining = Decimal(str(inner.get("sz", "0")))
        filled = orig - remaining
        qty = orig
    else:
        remaining = qty - filled
    side_raw = inner.get("side") or inner.get("b")
    if side_raw in (True, "B", "BUY", "buy"):
        side = OrderSide.BUY
    elif side_raw in (False, "A", "SELL", "sell"):
        side = OrderSide.SELL
    else:
        side = OrderSide.BUY if inner.get("isBuy") else OrderSide.SELL
    tif = None
    order_type_raw = inner.get("orderType") or inner.get("order_type")
    if isinstance(order_type_raw, dict) and "limit" in order_type_raw:
        tif = order_type_raw["limit"].get("tif")
    order_type = OrderType.MARKET if tif == "Ioc" else OrderType.LIMIT
    ts = inner.get("timestamp") or raw.get("statusTimestamp") or raw.get("time")
    timestamp = datetime.fromtimestamp(ts / 1000, tz=timezone.utc) if isinstance(ts, (int, float)) else datetime.now(timezone.utc)
    # v2.16.0 buy()/sell() send cloid as `0x` + md5(hbot_id).hexdigest() (32 hex chars, 34 total).
    # Exchange orderUpdates/orderStatus echo `order.cloid` as that same string, or omit it.
    cloid_raw = inner.get("cloid") if inner.get("cloid") not in (None, "") else raw.get("cloid")
    cloid = "" if cloid_raw in (None, "") else str(cloid_raw)
    return ExchangeOrder(
        exchange_order_id=str(inner.get("oid")) if inner.get("oid") is not None else None,
        cloid=cloid,
        symbol=to_pair_symbol(str(inner.get("coin") or inner.get("symbol") or ""), configured_pair=configured_pair),
        side=side,
        order_type=order_type,
        price=Decimal(str(inner["limitPx"])) if inner.get("limitPx") is not None else None,
        quantity=qty,
        filled_quantity=filled,
        remaining_quantity=remaining,
        reduce_only=bool(inner.get("reduceOnly") or inner.get("reduce_only")),
        status=HB_ORDER_STATE.get(status_raw, OrderStatus.UNKNOWN),
        timestamp=timestamp,
    )


def map_hummingbot_fill(raw: dict, *, configured_pair: str = "BTC-USD") -> ExchangeFill:
    side = OrderSide.BUY if str(raw.get("side", "")).lower() in {"b", "buy"} else OrderSide.SELL
    ts = raw.get("time")
    timestamp = datetime.fromtimestamp(ts / 1000, tz=timezone.utc) if isinstance(ts, (int, float)) else datetime.now(timezone.utc)
    return ExchangeFill(
        fill_id=str(raw.get("tid") or raw.get("fill_id") or raw.get("hash") or "0"),
        order_id=str(raw["oid"]) if raw.get("oid") is not None else None,
        cloid="" if raw.get("cloid") in (None, "") else str(raw.get("cloid")),
        symbol=to_pair_symbol(str(raw.get("coin") or raw.get("symbol") or ""), configured_pair=configured_pair),
        side=side,
        price=Decimal(str(raw.get("px") or raw.get("price") or "0")),
        quantity=Decimal(str(raw.get("sz") or raw.get("quantity") or "0")),
        fee=Decimal(str(raw.get("fee") or "0")),
        timestamp=timestamp,
    )
