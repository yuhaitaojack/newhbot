from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from app.protocol import OrderSide, OrderStatus, OrderType


class ConnectorBridge(Protocol):
    """Narrow seam over Hummingbot HyperliquidPerpetualDerivative.

    Adapter must call place() with OUR cloid. Never connector.buy()/sell(),
    which mint a new MD5 cloid on every invocation (v2.16.0).
    """

    place_calls: int

    async def rest_snapshot(self) -> dict: ...
    async def place(self, wire: dict) -> dict: ...
    async def cancel(self, cloid: str) -> dict: ...
    async def get_order(self, cloid: str) -> dict | None: ...
    async def get_fills(self) -> list[dict]: ...
    async def set_leverage(self, symbol: str, leverage: int) -> None: ...


class FakeConnector:
    """Deterministic stand-in. Does not import Hummingbot or talk to Hyperliquid."""

    def __init__(self) -> None:
        self.place_calls = 0
        self.cancel_calls = 0
        self.leverage_calls: list[tuple[str, int]] = []
        self.wire_orders: list[dict] = []
        self.orders: dict[str, dict] = {}
        self.fills: list[dict] = []
        self.asset_positions: list[dict] = []
        self.hummingbot_account_positions: list[dict] | None = None
        self.account = {"equity": "10000", "available": "10000", "margin_used": "0"}
        self.mid = Decimal("100")
        self.raise_on_place = False
        self.raise_on_query = False

    async def rest_snapshot(self) -> dict:
        if self.raise_on_query:
            raise TimeoutError("fake connector snapshot failed")
        hb = self.hummingbot_account_positions if self.hummingbot_account_positions is not None else self.asset_positions
        return {
            "assetPositions": self.asset_positions,
            "hummingbotPositions": hb,
            "openOrders": list(self.orders.values()),
            "fills": list(self.fills),
            "account": self.account,
            "mid": str(self.mid),
        }

    async def place(self, wire: dict) -> dict:
        self.place_calls += 1
        self.wire_orders.append(dict(wire))
        if self.raise_on_place:
            raise TimeoutError("fake connector place failed")
        cloid = wire["cloid"]
        if cloid in self.orders:
            return {"duplicate": True, "order": self.orders[cloid]}
        oid = str(len(self.orders) + 1)
        order = {
            "cloid": cloid,
            "oid": oid,
            "coin": wire["symbol"].replace("-USD", ""),
            "symbol": wire["symbol"],
            "side": "BUY" if wire["is_buy"] else "SELL",
            "sz": "0" if not wire.get("leave_open") else str(wire["sz"]),
            "origSz": str(wire["sz"]),
            "limitPx": str(wire["limit_px"]),
            "reduceOnly": wire["reduce_only"],
            "status": "filled" if not wire.get("leave_open") else "open",
            "orderType": {"limit": {"tif": wire.get("tif", "Ioc")}},
        }
        self.orders[cloid] = order
        if order["status"] == "filled":
            self.fills.append(
                {
                    "tid": oid,
                    "oid": oid,
                    "cloid": cloid,
                    "coin": order["coin"],
                    "side": "B" if wire["is_buy"] else "A",
                    "px": str(wire["limit_px"]),
                    "sz": str(wire["sz"]),
                    "fee": "0",
                }
            )
            szi = Decimal(str(wire["sz"])) if wire["is_buy"] else -Decimal(str(wire["sz"]))
            if wire["reduce_only"]:
                self.asset_positions = []
            else:
                self.asset_positions = [
                    {
                        "type": "oneWay",
                        "position": {
                            "coin": order["coin"],
                            "szi": str(szi),
                            "entryPx": str(wire["limit_px"]),
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
