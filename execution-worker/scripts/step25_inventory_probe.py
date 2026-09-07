"""STEP 2.5 official-image inventory. No orders, no keys, no user address.

trading_required=False instantiate + public-safe attribute inspection.
Does not call buy/sell/_place_order/cancel/set_leverage.
"""

from __future__ import annotations

import inspect
import json
import sys
import traceback


def _safe_len(obj) -> int | str:
    try:
        return len(obj)
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def main() -> int:
    report: dict = {
        "python": sys.version,
        "python_major_minor": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "hummingbot_version_file": None,
        "imports": {},
        "instantiate_ok": False,
        "error": None,
    }
    try:
        version_path = "/home/hummingbot/hummingbot/VERSION"
        try:
            with open(version_path, encoding="utf-8") as fh:
                report["hummingbot_version_file"] = fh.read().strip()
        except Exception as exc:
            report["hummingbot_version_file"] = f"{type(exc).__name__}: {exc}"

        from hummingbot.connector.derivative.hyperliquid_perpetual.hyperliquid_perpetual_derivative import (
            HyperliquidPerpetualDerivative,
        )
        from hummingbot.connector.exchange_py_base import ExchangePyBase
        from hummingbot.connector.client_order_tracker import ClientOrderTracker
        from hummingbot.connector.perpetual_trading import PerpetualTrading
        from hummingbot.core.data_type.common import PositionMode
        from hummingbot.core.event.events import MarketEvent

        report["imports"] = {
            "HyperliquidPerpetualDerivative": True,
            "ExchangePyBase": True,
            "ClientOrderTracker": True,
            "PerpetualTrading": True,
            "MarketEvent": True,
            "is_subclass_exchange_py_base": issubclass(HyperliquidPerpetualDerivative, ExchangePyBase),
            "is_subclass_perpetual_trading": issubclass(HyperliquidPerpetualDerivative, PerpetualTrading),
        }
        report["market_event_members"] = [item.name for item in MarketEvent]
        report["has_order_filled"] = hasattr(MarketEvent, "OrderFilled")
        report["has_order_completed"] = hasattr(MarketEvent, "BuyOrderCompleted") and hasattr(
            MarketEvent, "SellOrderCompleted"
        )
        report["has_order_cancelled"] = hasattr(MarketEvent, "OrderCancelled")
        report["has_order_failure"] = hasattr(MarketEvent, "OrderFailure")
        report["add_listener_present"] = hasattr(HyperliquidPerpetualDerivative, "add_listener")
        report["client_order_tracker_class"] = ClientOrderTracker.__name__

        params = list(inspect.signature(HyperliquidPerpetualDerivative.__init__).parameters)
        report["constructor_params"] = params

        connector = HyperliquidPerpetualDerivative(
            trading_required=False,
            trading_pairs=["BTC-USD"],
            hyperliquid_perpetual_secret_key=None,
            hyperliquid_perpetual_address=None,
        )
        report["instantiate_ok"] = True
        report["trading_required"] = bool(connector.is_trading_required)
        report["authenticator_is_none"] = connector.authenticator is None
        modes = [str(item) for item in connector.supported_position_modes()]
        report["supported_position_modes"] = modes
        report["oneway_present"] = PositionMode.ONEWAY in connector.supported_position_modes()
        report["hedge_present"] = any("HEDGE" in item.upper() for item in modes)
        report["account_positions_len"] = _safe_len(getattr(connector, "account_positions", None))
        report["in_flight_orders_len"] = _safe_len(getattr(connector, "in_flight_orders", None))
        report["trading_rules_len_before_network"] = _safe_len(getattr(connector, "trading_rules", None))
        report["has_quantize_order_price"] = callable(getattr(connector, "quantize_order_price", None))
        report["has_quantize_order_amount"] = callable(getattr(connector, "quantize_order_amount", None))
        report["has_start_network"] = callable(getattr(connector, "start_network", None))
        report["has_stop_network"] = callable(getattr(connector, "stop_network", None))
        report["order_tracker_type"] = type(getattr(connector, "_order_tracker", None)).__name__

        # Source facts for retry / second cloid (no live call).
        place_src = inspect.getsource(HyperliquidPerpetualDerivative._place_order)
        buy_src = inspect.getsource(HyperliquidPerpetualDerivative.buy)
        sell_src = inspect.getsource(HyperliquidPerpetualDerivative.sell)
        report["place_source_has_cloid_order_id"] = '"cloid": order_id' in place_src or "'cloid': order_id" in place_src
        report["place_source_mentions_retry"] = "retry" in place_src.lower()
        report["place_source_mentions_renew"] = "renew" in place_src.lower()
        report["buy_mints_new_client_order_id"] = "get_new_client_order_id" in buy_src or "hashlib.md5" in buy_src
        report["sell_mints_new_client_order_id"] = "get_new_client_order_id" in sell_src or "hashlib.md5" in sell_src
        report["buy_calls_create_order"] = "_create_order" in buy_src
        report["sell_calls_create_order"] = "_create_order" in sell_src
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
        print(json.dumps(report, indent=2, default=str))
        return 1
    print(json.dumps(report, indent=2, default=str))
    if report["hummingbot_version_file"] != "2.16.0":
        return 2
    if report["trading_required"] or not report["authenticator_is_none"]:
        return 3
    if not report["oneway_present"] or report["hedge_present"]:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
