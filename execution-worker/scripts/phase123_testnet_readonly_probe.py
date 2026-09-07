from __future__ import annotations

import asyncio
import json

from app.config import load_config
from app.factory import build_runtime
from app.open_order_precheck import snapshot_open_orders


async def main() -> None:
    runtime = build_runtime(load_config())
    await runtime.connect()
    try:
        balance = await runtime.get_balance()
        positions = await runtime.get_positions()
        orders = await runtime.get_open_orders()
        market = await runtime.get_market_data("BTC-USD")
        candles = await runtime.get_candles("BTC-USD", "5m", 5)
        connector = runtime.inner.connector
        precheck = await snapshot_open_orders(connector._inner(), configured_pair="BTC-USD")
        health = runtime.health_payload()
        runtime.heartbeat()
        health_after_heartbeat = runtime.health_payload()
        print(
            json.dumps(
                {
                    "domain": runtime.config.hyperliquid_domain,
                    "state": runtime.worker_state().value,
                    "sync": runtime.sync_status().value,
                    "health_ready_without_heartbeat": bool(health["ready"]),
                    "backend_heartbeat_ok": bool(health["backend_heartbeat_ok"]),
                    "health_ready_with_heartbeat": bool(health_after_heartbeat["ready"]),
                    "authenticated": bool(getattr(connector, "authenticated", False)),
                    "account_read": getattr(connector, "account_read", None),
                    "balance_keys": sorted(balance.model_dump().keys()),
                    "positions_count": len(positions),
                    "open_orders_count": len(orders),
                    "market_data_keys": sorted(market.keys()),
                    "candle_count": len(candles),
                    "candle_keys": sorted(candles[0].keys()) if candles else [],
                    "open_order_precheck_status": precheck["status"],
                    "open_order_precheck_configured_count": precheck["configured_open_count"],
                    "open_order_precheck_other_count": precheck["other_open_count"],
                }
            )
        )
    finally:
        await runtime.disconnect()


asyncio.run(main())
