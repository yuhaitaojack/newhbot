from __future__ import annotations

from typing import Any

from app.readonly_guard import ReadOnlyGuard, ReadOnlyViolation


def try_load_hummingbot_connector_class():
    """Import HyperliquidPerpetualDerivative from Hummingbot v2.16.0. None if absent."""
    try:
        from hummingbot.connector.derivative.hyperliquid_perpetual.hyperliquid_perpetual_derivative import (
            HyperliquidPerpetualDerivative,
        )

        return HyperliquidPerpetualDerivative
    except Exception:
        return None


def instantiate_readonly(cls: type, trading_pairs: list[str]) -> Any:
    """Instantiate with v2.16.0 trading_required=False. No secret key, no address.

    Source (v2.16.0 HyperliquidPerpetualDerivative): authenticator is None when
    _trading_required is False. start_network then skips user stream, status
    polling, and builder-fee init.
    """
    return cls(
        trading_required=False,
        trading_pairs=list(trading_pairs),
        hyperliquid_perpetual_secret_key=None,
        hyperliquid_perpetual_address=None,
    )


def wrap_readonly(connector: Any) -> ReadOnlyGuard:
    return connector if isinstance(connector, ReadOnlyGuard) else ReadOnlyGuard(connector)


class ReadOnlyHummingbotBridge:
    """ConnectorBridge that never places, cancels, or changes leverage.

    Account / user-stream reads need a Hyperliquid user address. PHASE 4 does not
    query a real trading account. Public instrument metadata is fetched separately.
    """

    read_only = True
    has_user_stream = False
    place_calls = 0

    def __init__(self, connector: Any) -> None:
        self.connector = wrap_readonly(connector)
        self.account_read = "skipped_no_user_address"

    async def rest_snapshot(self) -> dict:
        return {
            "assetPositions": [],
            "hummingbotPositions": [],
            "openOrders": [],
            "fills": [],
            "account": {},
            "mid": "0",
            "account_read": self.account_read,
        }

    async def place(self, wire: dict) -> dict:
        _ = wire
        self.place_calls += 1
        raise ReadOnlyViolation("PHASE 4 read-only forbids place")

    async def cancel(self, cloid: str) -> dict:
        _ = cloid
        raise ReadOnlyViolation("PHASE 4 read-only forbids cancel")

    async def get_order(self, cloid: str) -> dict | None:
        _ = cloid
        return None

    async def get_fills(self) -> list[dict]:
        return []

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        _ = symbol, leverage
        raise ReadOnlyViolation("PHASE 4 read-only forbids set_leverage")
