from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from app.exchange_models import InstrumentMeta
from app.hummingbot_place import place_with_injected_cloid
from app.instrument_meta import default_btc_instrument_meta
from app.protocol import OrderSide, OrderStatus, OrderType
from app.quantization import QuantizeReject, quantize_order_price, quantize_order_size


class ConnectorBridge(Protocol):
    """Narrow seam over Hummingbot HyperliquidPerpetualDerivative.

    Adapter must call place() with OUR cloid. Never connector.buy()/sell(),
    which mint a new MD5 cloid on every invocation (v2.16.0).
    """

    place_calls: int
    ws_connected: bool

    async def start_network(self) -> None: ...
    async def stop_network(self) -> None: ...
    async def rest_snapshot(self) -> dict: ...
    async def place(self, wire: dict) -> dict: ...
    async def cancel(self, cloid: str) -> dict: ...
    async def get_order(self, cloid: str) -> dict | None: ...
    async def get_fills(self) -> list[dict]: ...
    async def set_leverage(self, symbol: str, leverage: int) -> None: ...
    def quantize_order_price(self, trading_pair: str, price: Decimal) -> Decimal: ...
    def quantize_order_amount(self, trading_pair: str, amount: Decimal) -> Decimal: ...
    def trading_rule(self, trading_pair: str) -> InstrumentMeta: ...


class FakeConnector:
    """Deterministic stand-in for HyperliquidPerpetualDerivative.

    Does not import Hummingbot or talk to Hyperliquid. Holds the execution-layer
    truth the same way the real connector would: positions, in-flight orders,
    fills, trading rules, network flag. Mock ≠ production Hyperliquid.
    """

    def __init__(self) -> None:
        self.place_calls = 0
        self.cancel_calls = 0
        self.leverage_calls: list[tuple[str, int]] = []
        self.wire_orders: list[dict] = []
        self.orders: dict[str, dict] = {}
        self.fills: list[dict] = []
        self._fill_ids: set[str] = set()
        self.asset_positions: list[dict] = []
        self.account = {"equity": "10000", "available": "10000", "margin_used": "0"}
        self.mid = Decimal("100")
        self.raise_on_place = False
        self.raise_on_query = False
        self.ws_connected = False
        self.read_only = False
        self.has_user_stream = True
        self._trading_rules: dict[str, InstrumentMeta] = {
            "BTC-USD": default_btc_instrument_meta(),
        }

    @property
    def account_positions(self) -> list[dict]:
        return self.asset_positions

    @property
    def in_flight_orders(self) -> dict[str, dict]:
        return self.orders

    def trading_rule(self, trading_pair: str) -> InstrumentMeta:
        if trading_pair not in self._trading_rules:
            self._trading_rules[trading_pair] = default_btc_instrument_meta().model_copy(
                update={"symbol": trading_pair}
            )
        return self._trading_rules[trading_pair]

    def quantize_order_price(self, trading_pair: str, price: Decimal) -> Decimal:
        return quantize_order_price(Decimal(str(price)), self.trading_rule(trading_pair).tick_size)

    def quantize_order_amount(self, trading_pair: str, amount: Decimal) -> Decimal:
        qty = quantize_order_size(Decimal(str(amount)), self.trading_rule(trading_pair).step_size)
        if qty <= 0:
            raise QuantizeReject("quantity quantized to zero")
        return qty

    def buy(self, *args, **kwargs):
        raise AssertionError("buy() is forbidden; v2.16.0 mints a new MD5 cloid")

    def sell(self, *args, **kwargs):
        raise AssertionError("sell() is forbidden; v2.16.0 mints a new MD5 cloid")

    async def start_network(self) -> None:
        self.ws_connected = True

    async def stop_network(self) -> None:
        self.ws_connected = False

    def record_fill(self, fill: dict) -> None:
        tid = str(fill.get("tid") or fill.get("fill_id") or "")
        if tid and tid in self._fill_ids:
            return
        if tid:
            self._fill_ids.add(tid)
        self.fills.append(fill)

    async def rest_snapshot(self) -> dict:
        if self.raise_on_query:
            raise TimeoutError("fake connector snapshot failed")
        return {
            "assetPositions": self.asset_positions,
            "openOrders": list(self.orders.values()),
            "fills": list(self.fills),
            "account": self.account,
            "mid": str(self.mid),
        }

    async def place(self, wire: dict) -> dict:
        self.wire_orders.append(dict(wire))
        if self.raise_on_place:
            self.place_calls += 1
            raise TimeoutError("fake connector place failed")
        return await place_with_injected_cloid(self, wire)

    async def _place_order(
        self,
        order_id: str,
        trading_pair: str,
        amount: Decimal,
        trade_type,
        order_type,
        price: Decimal,
        position_action: str | None = None,
        **kwargs,
    ) -> dict:
        """Stand-in for v2.16.0 HyperliquidPerpetualDerivative._place_order.

        Uses the caller ``order_id`` as cloid. No second id, no retry.
        """
        _ = kwargs
        self.place_calls += 1
        cloid = str(order_id)
        if cloid in self.orders:
            return {"duplicate": True, "order": self.orders[cloid]}
        oid = str(len(self.orders) + 1)
        is_buy = str(trade_type).upper() in {"BUY", "TRADETYPE.BUY"}
        reduce_only = str(position_action).upper() in {"CLOSE", "POSITIONACTION.CLOSE"}
        tif = "Ioc" if str(order_type).upper() in {"MARKET", "ORDERTYPE.MARKET"} else "Gtc"
        coin = trading_pair.replace("-USD", "")
        remaining = "0"
        status = "filled"
        order = {
            "cloid": cloid,
            "oid": oid,
            "coin": coin,
            "symbol": trading_pair,
            "side": "BUY" if is_buy else "SELL",
            "sz": remaining,
            "origSz": str(amount),
            "limitPx": str(price),
            "reduceOnly": reduce_only,
            "status": status,
            "orderType": {"limit": {"tif": tif}},
        }
        self.orders[cloid] = order
        self.record_fill(
            {
                "tid": oid,
                "oid": oid,
                "cloid": cloid,
                "coin": coin,
                "side": "B" if is_buy else "A",
                "px": str(price),
                "sz": str(amount),
                "fee": "0",
            }
        )
        szi = Decimal(str(amount)) if is_buy else -Decimal(str(amount))
        if reduce_only:
            self.asset_positions = []
        else:
            self.asset_positions = [
                {
                    "type": "oneWay",
                    "position": {
                        "coin": coin,
                        "szi": str(szi),
                        "entryPx": str(price),
                        "unrealizedPnl": "0",
                        "leverage": {"value": "1"},
                    },
                }
            ]
        return {"order": order}

    async def cancel(self, cloid: str) -> dict:
        self.cancel_calls += 1
        order = self.orders.get(cloid)
        if order is None:
            return {"ok": False}
        order["status"] = "canceled"
        return {"ok": True, "order": order}

    async def get_order(self, cloid: str) -> dict | None:
        if self.raise_on_query:
            raise TimeoutError("fake connector get_order failed")
        return self.orders.get(cloid)

    async def get_fills(self) -> list[dict]:
        if self.raise_on_query:
            raise TimeoutError("fake connector get_fills failed")
        return list(self.fills)

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        self.leverage_calls.append((symbol, leverage))


def try_load_hummingbot_connector_class():
    """Optional. Default worker path does not import or instantiate this."""
    from app.hummingbot_readonly import try_load_hummingbot_connector_class as _load

    return _load()


# Imported by mapping tests; not used as a trading path.
_ = (OrderSide, OrderStatus, OrderType)
