"""STEP 2.5 public read-only runtime. No keys, no user address, no orders."""

from __future__ import annotations

import asyncio
import json
import traceback
from decimal import Decimal


async def main() -> dict:
    report: dict = {
        "network_check": None,
        "trading_rules": None,
        "btc_meta": None,
        "quantize_order_price": None,
        "quantize_order_amount": None,
        "account_positions": None,
        "in_flight_orders": None,
        "start_network_readonly": None,
        "user_stream_started": None,
        "status_polling_started": None,
        "stop_network": None,
        "error": None,
    }
    try:
        from hummingbot.connector.derivative.hyperliquid_perpetual.hyperliquid_perpetual_derivative import (
            HyperliquidPerpetualDerivative,
        )

        connector = HyperliquidPerpetualDerivative(
            trading_required=False,
            trading_pairs=["BTC-USD"],
            hyperliquid_perpetual_secret_key=None,
            hyperliquid_perpetual_address=None,
        )
        report["authenticator_is_none"] = connector.authenticator is None
        report["trading_required"] = bool(connector.is_trading_required)
        report["account_positions"] = list(getattr(connector, "account_positions", {}) or {})
        report["in_flight_orders"] = list(getattr(connector, "in_flight_orders", {}) or {})

        try:
            await asyncio.wait_for(connector._make_network_check_request(), timeout=20)
            report["network_check"] = "ok"
        except Exception as exc:
            report["network_check"] = f"{type(exc).__name__}: {exc}"

        try:
            info = await asyncio.wait_for(connector._make_trading_rules_request(), timeout=20)
            rules = await connector._format_trading_rules(info)
            connector._trading_rules = {item.trading_pair: item for item in rules}
            report["trading_rules"] = len(rules)
            btc = connector._trading_rules.get("BTC-USD")
            if btc is not None:
                report["btc_meta"] = {
                    "trading_pair": btc.trading_pair,
                    "min_base_amount_increment": str(btc.min_base_amount_increment),
                    "min_price_increment": str(btc.min_price_increment),
                    "min_order_size": str(btc.min_order_size),
                    "min_notional_size": str(btc.min_notional_size),
                }
                px = connector.quantize_order_price("BTC-USD", Decimal("100.16"))
                amt = connector.quantize_order_amount("BTC-USD", Decimal("0.000019"))
                report["quantize_order_price"] = str(px)
                report["quantize_order_amount"] = str(amt)
        except Exception as exc:
            report["trading_rules"] = f"{type(exc).__name__}: {exc}"

        try:
            await asyncio.wait_for(connector.start_network(), timeout=25)
            report["start_network_readonly"] = "ok"
            report["user_stream_started"] = connector._user_stream_tracker_task is not None
            report["status_polling_started"] = connector._status_polling_task is not None
            await asyncio.wait_for(connector.stop_network(), timeout=15)
            report["stop_network"] = "ok"
        except Exception as exc:
            report["start_network_readonly"] = f"{type(exc).__name__}: {exc}"
            try:
                await asyncio.wait_for(connector.stop_network(), timeout=10)
                report["stop_network"] = "ok-after-error"
            except Exception as stop_exc:
                report["stop_network"] = f"{type(stop_exc).__name__}: {stop_exc}"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
    return report


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), indent=2, default=str))
