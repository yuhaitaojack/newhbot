"""STEP 4 authenticated read-only probe. Run in the Worker image.

Never prints secrets, addresses, or private keys.
Never successfully places, cancels, or sets leverage.
"""

from __future__ import annotations

import asyncio
import json
import sys
from decimal import Decimal


def _safe_side(pos) -> str:
    return str(getattr(pos, "side", ""))


async def _run() -> dict:
    from app.config import WorkerConfig
    from app.factory import build_runtime
    from app.hummingbot_readonly import credentials_supplied
    from app.hyperliquid_adapter import ExecutionDisabled
    from app.protocol import OrderSide, OrderType, PlaceOrderRequest
    from app.readonly_guard import ReadOnlyViolation

    report: dict = {
        "credentials_supplied": credentials_supplied(),
        "execution_enabled": False,
        "account_connection": "BLOCKED",
        "authenticated": False,
        "write_loops_disabled": False,
        "user_stream_task": False,
        "guard_blocks": {},
        "position_count": None,
        "position_sides": [],
        "position_symbols": [],
        "foreign_symbols": [],
        "recovery_reason": None,
        "worker_state": None,
        "open_order_count": None,
        "fill_count": None,
        "account_read": None,
        "place_blocked": False,
        "cancel_blocked": False,
        "leverage_blocked": False,
        "error_type": None,
    }
    if not credentials_supplied():
        return report

    cfg = WorkerConfig(mode="hyperliquid", execution_enabled=False, trading_pair="BTC-USD")
    runtime = build_runtime(cfg)
    inner = runtime.inner
    bridge = inner.connector
    report["authenticated"] = bool(getattr(bridge, "authenticated", False))
    report["write_loops_disabled"] = bool(getattr(bridge, "write_loops_disabled", False))
    guard = getattr(bridge, "connector", None)
    blocks: dict[str, str] = {}
    for name in ("buy", "sell", "_place_order", "cancel", "set_leverage", "_execute_order_cancel"):
        try:
            result = getattr(guard, name)()
            if asyncio.iscoroutine(result):
                await result
            blocks[name] = "NOT_BLOCKED"
        except ReadOnlyViolation:
            blocks[name] = "ReadOnlyViolation"
        except Exception as exc:
            blocks[name] = type(exc).__name__
    report["guard_blocks"] = blocks

    try:
        await inner.connect()
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        report["account_connection"] = "BLOCKED"
        return report

    report["account_read"] = getattr(bridge, "account_read", None)
    report["user_stream_task"] = bool(getattr(bridge, "has_user_stream", False))
    report["recovery_reason"] = getattr(inner, "recovery_reason", None)
    report["foreign_symbols"] = list(getattr(inner, "foreign_symbols", []) or [])
    report["worker_state"] = inner.worker_state().value
    positions = await inner.get_positions()
    report["position_count"] = len(positions)
    report["position_sides"] = [_safe_side(item) for item in positions]
    report["position_symbols"] = [str(item.symbol) for item in positions]
    orders = await inner.get_open_orders()
    report["open_order_count"] = len(orders)
    fills = await inner.get_fills()
    report["fill_count"] = len(fills)

    placed = await inner.place_order(
        PlaceOrderRequest(
            request_id="step4-readonly",
            cloid="0x" + "d" * 32,
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.001"),
            reduce_only=False,
        )
    )
    status = getattr(placed.status, "value", str(placed.status))
    report["place_blocked"] = status in {"REJECTED", "rejected"}
    report["place_error_is_readonly"] = "read-only" in str(placed.error or "") or "execution disabled" in str(
        placed.error or ""
    )
    try:
        await inner.cancel_order("0x" + "d" * 32, "step4-readonly")
        report["cancel_blocked"] = False
    except (ReadOnlyViolation, ExecutionDisabled):
        report["cancel_blocked"] = True
    try:
        await inner.set_leverage("BTC-USD", 2)
        report["leverage_blocked"] = False
    except (ReadOnlyViolation, ExecutionDisabled):
        report["leverage_blocked"] = True
    try:
        await inner.disconnect()
    except Exception:
        pass
    if report["account_read"] == "authenticated":
        report["account_connection"] = "VERIFIED"
    else:
        report["account_connection"] = "NOT VERIFIED"
    return report


def main() -> int:
    report = asyncio.run(_run())
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
