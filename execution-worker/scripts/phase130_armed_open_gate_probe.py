from __future__ import annotations

import asyncio
import json
from decimal import Decimal

from app.config import load_config
from app.factory import build_runtime
from app.protocol import OrderSide, OrderType, PlaceOrderRequest


async def main() -> None:
    runtime = build_runtime(load_config())
    await runtime.connect()
    try:
        request = PlaceOrderRequest(
            request_id="phase130-open-gate",
            cloid="0x" + "9a" * 16,
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00001"),
            price=Decimal("1"),
            reduce_only=False,
        )
        result = await runtime.place_order(request)
        print(
            json.dumps(
                {
                    "domain": runtime.config.hyperliquid_domain,
                    "worker_state": runtime.worker_state().value,
                    "backend_heartbeat_ok": runtime.backend_heartbeat_ok,
                    "result_status": result.status.value,
                    "result_error": result.error,
                    "bridge_place_calls": getattr(runtime.inner.connector, "place_calls", 0),
                }
            )
        )
    finally:
        await runtime.disconnect()


asyncio.run(main())
