"""One-shot read-only open-order precheck.

Uses the Hummingbot v2.16.0 Connector `_api_post` transport already used for
`clearinghouseState` / `orderStatus`. Calls Hyperliquid official public info
`type=openOrders`. Does not persist, does not update OrderTracker, does not
cancel, and is not part of the production order state machine.
"""

from __future__ import annotations

from typing import Any

from app.mapping import to_pair_symbol

# Official Hyperliquid info type. Not present as a Hummingbot constant in v2.16.0.
HL_OPEN_ORDERS_TYPE = "openOrders"
# Same path_url HyperliquidPerpetualDerivative._update_balances uses (ACCOUNT_INFO_URL).
HL_INFO_PATH = "/info"


def _coin(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    return str(row.get("coin") or "")


async def snapshot_open_orders(inner: Any, *, configured_pair: str = "BTC-USD") -> dict:
    """Return a throwaway snapshot. Never stores rows on `inner`."""
    report: dict = {
        "status": "NOT_AVAILABLE",
        "source": "hyperliquid_info_openOrders_via_connector_api_post",
        "configured_pair": configured_pair,
        "configured_open_count": None,
        "other_open_count": None,
        "other_coins": [],
        "persisted": False,
        "blocking": True,
        "error_type": None,
    }
    post = getattr(inner, "_api_post", None)
    address = str(getattr(inner, "hyperliquid_perpetual_address", "") or "").strip()
    if not callable(post):
        report["error_type"] = "api_post_missing"
        return report
    if not address:
        report["error_type"] = "address_missing"
        return report
    try:
        raw = await post(
            path_url=HL_INFO_PATH,
            data={"type": HL_OPEN_ORDERS_TYPE, "user": address},
            is_auth_required=False,
        )
    except Exception as exc:
        report["status"] = "FAILED"
        report["error_type"] = type(exc).__name__
        return report
    if not isinstance(raw, list):
        report["status"] = "FAILED"
        report["error_type"] = "unexpected_payload"
        return report
    configured = 0
    other = 0
    other_coins: list[str] = []
    for row in raw:
        coin = _coin(row)
        pair = to_pair_symbol(coin, configured_pair=configured_pair)
        if pair == configured_pair:
            configured += 1
        else:
            other += 1
            if coin and coin not in other_coins:
                other_coins.append(coin)
    report["status"] = "VERIFIED"
    report["configured_open_count"] = configured
    report["other_open_count"] = other
    report["other_coins"] = other_coins
    report["blocking"] = configured > 0
    report["error_type"] = None
    return report
