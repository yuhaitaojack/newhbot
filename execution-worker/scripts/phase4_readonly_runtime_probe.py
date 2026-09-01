"""PHASE 4 public read-only runtime probe. No orders, no keys, no user address."""

from __future__ import annotations

import asyncio
import json
import traceback


async def main() -> dict:
    report: dict = {
        "network_check": None,
        "trading_rules": None,
        "btc_meta": None,
        "start_network": None,
        "user_stream_started": None,
        "stop_network": None,
        "forbidden_called": [],
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

        try:
            await asyncio.wait_for(connector._make_network_check_request(), timeout=20)
            report["network_check"] = "ok"
        except Exception as exc:
            report["network_check"] = f"{type(exc).__name__}: {exc}"

        try:
            info = await asyncio.wait_for(connector._make_trading_rules_request(), timeout=20)
            rules = await connector._format_trading_rules(info)
            report["trading_rules"] = len(rules)
            btc = next((item for item in rules if item.trading_pair == "BTC-USD"), None)
            if btc is not None:
                report["btc_meta"] = {
                    "trading_pair": btc.trading_pair,
                    "min_base_amount_increment": str(btc.min_base_amount_increment),
                    "min_price_increment": str(btc.min_price_increment),
                    "min_order_size": str(btc.min_order_size),
                    "min_notional_size": str(btc.min_notional_size),
                }
        except Exception as exc:
            report["trading_rules"] = f"{type(exc).__name__}: {exc}"

        try:
            await asyncio.wait_for(connector.start_network(), timeout=25)
            report["start_network"] = "ok"
            report["user_stream_started"] = connector._user_stream_tracker_task is not None
            report["status_polling_started"] = connector._status_polling_task is not None
            await asyncio.wait_for(connector.stop_network(), timeout=15)
            report["stop_network"] = "ok"
        except Exception as exc:
            report["start_network"] = f"{type(exc).__name__}: {exc}"
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
