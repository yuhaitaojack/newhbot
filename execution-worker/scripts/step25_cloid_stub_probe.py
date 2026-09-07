"""STEP 2.5 cloid injection against real v2.16.0 _place_order with stub transport.

Never performs Hyperliquid HTTP. Never uses keys. Never calls buy/sell.
"""

from __future__ import annotations

import asyncio
import json
import sys
import traceback
from decimal import Decimal
from pathlib import Path
from typing import Any

# Worker code is mounted at /tmp/worker when run in the official image.
sys.path.insert(0, "/tmp/worker")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main() -> dict:
    report: dict = {
        "adapter_helper_imported": False,
        "buy_calls": 0,
        "sell_calls": 0,
        "api_post_calls": 0,
        "place_calls": 0,
        "wire_cloid": None,
        "order_id_arg": None,
        "path_url": None,
        "second_cloid": False,
        "buy_called": False,
        "sell_called": False,
        "error": None,
    }
    try:
        from app.hummingbot_place import place_with_injected_cloid

        report["adapter_helper_imported"] = True
        from hummingbot.connector.derivative.hyperliquid_perpetual.hyperliquid_perpetual_derivative import (
            HyperliquidPerpetualDerivative,
        )

        connector = HyperliquidPerpetualDerivative(
            trading_required=False,
            trading_pairs=["BTC-USD"],
            hyperliquid_perpetual_secret_key=None,
            hyperliquid_perpetual_address=None,
        )

        posted: list[dict[str, Any]] = []
        buy_calls = {"n": 0}
        sell_calls = {"n": 0}

        async def stub_api_post(*args, **kwargs):
            data = kwargs.get("data")
            if data is None and len(args) >= 2:
                data = args[1]
            path_url = kwargs.get("path_url")
            if path_url is None and args:
                path_url = args[0]
            posted.append({"path_url": path_url, "data": data, "kwargs_keys": sorted(kwargs)})
            return {
                "status": "ok",
                "response": {"data": {"statuses": [{"resting": {"oid": 4242}}]}},
            }

        async def refuse_exchange_symbol(trading_pair: str):
            _ = trading_pair
            return "BTC"

        original_buy = connector.buy
        original_sell = connector.sell

        def guarded_buy(*args, **kwargs):
            buy_calls["n"] += 1
            raise AssertionError("buy() must not run during cloid stub proof")

        def guarded_sell(*args, **kwargs):
            sell_calls["n"] += 1
            raise AssertionError("sell() must not run during cloid stub proof")

        connector._api_post = stub_api_post  # type: ignore[method-assign]
        connector.coin_to_asset = {"BTC": 0}
        connector.exchange_symbol_associated_to_pair = refuse_exchange_symbol  # type: ignore[method-assign]
        connector.buy = guarded_buy  # type: ignore[method-assign]
        connector.sell = guarded_sell  # type: ignore[method-assign]
        _ = original_buy, original_sell

        cloid = "0x" + "ab" * 16
        wire = {
            "cloid": cloid,
            "symbol": "BTC-USD",
            "is_buy": True,
            "sz": "0.2",
            "limit_px": "105.0",
            "reduce_only": False,
            "tif": "Ioc",
        }
        result = await place_with_injected_cloid(connector, wire)
        report["place_result_oid"] = (result.get("order") or {}).get("oid")
        report["place_result_cloid"] = (result.get("order") or {}).get("cloid")
        report["api_post_calls"] = len(posted)
        report["buy_calls"] = buy_calls["n"]
        report["sell_calls"] = sell_calls["n"]
        report["buy_called"] = buy_calls["n"] > 0
        report["sell_called"] = sell_calls["n"] > 0
        if posted:
            payload = posted[0]["data"] or {}
            orders = payload.get("orders") if isinstance(payload, dict) else None
            report["path_url"] = posted[0]["path_url"]
            report["wire_cloid"] = orders.get("cloid") if isinstance(orders, dict) else None
            report["payload_type"] = payload.get("type") if isinstance(payload, dict) else None
        report["order_id_arg"] = cloid
        report["second_cloid"] = bool(report["wire_cloid"] and report["wire_cloid"] != cloid)
        report["md5_like_mismatch"] = report["second_cloid"]

        # Second invocation is the helper being called again by the test, not an inner retry.
        result2 = await place_with_injected_cloid(connector, wire)
        _ = result2
        report["api_post_calls_after_second_helper_invoke"] = len(posted)
        report["inner_retry_on_single_call"] = len(posted) >= 1 and report["api_post_calls"] != 1
        report["helper_has_no_inner_retry"] = report["api_post_calls"] == 1
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
    return report


if __name__ == "__main__":
    payload = asyncio.run(main())
    print(json.dumps(payload, indent=2, default=str))
    if payload.get("error"):
        raise SystemExit(1)
    if payload.get("buy_called") or payload.get("sell_called"):
        raise SystemExit(2)
    if payload.get("api_post_calls") != 1:
        raise SystemExit(3)
    if payload.get("wire_cloid") != payload.get("order_id_arg"):
        raise SystemExit(4)
    if payload.get("second_cloid"):
        raise SystemExit(5)
    raise SystemExit(0)
