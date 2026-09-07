"""STEP 4 live authenticated read-only probe. Official HB Worker image only.

Never prints secrets or private keys.
Never places, cancels, closes, or sets leverage on the exchange.
Write loops must be disabled before start_network.
"""

from __future__ import annotations

import asyncio
import json
import sys
from decimal import Decimal


def _side(pos) -> str:
    return str(getattr(pos, "side", ""))


def _pos_row(pos) -> dict:
    return {
        "symbol": str(getattr(pos, "symbol", "")),
        "side": _side(pos),
        "size": str(getattr(pos, "size", "")),
        "entry_price": str(getattr(pos, "entry_price", "")),
    }


async def _run() -> dict:
    from app.config import WorkerConfig
    from app.factory import build_runtime
    from app.hummingbot_readonly import credentials_supplied
    from app.hyperliquid_adapter import ExecutionDisabled
    from app.protocol import OrderSide, OrderType, PlaceOrderRequest, PositionSide
    from app.readonly_guard import ReadOnlyViolation

    report: dict = {
        "credentials_supplied": credentials_supplied(),
        "execution_enabled": False,
        "account_connection": "BLOCKED",
        "authenticated": False,
        "trading_required": None,
        "authenticator_present": None,
        "write_loops_disabled_before_start": False,
        "user_stream_task": False,
        "user_stream_initialized": None,
        "ws_connected": False,
        "guard_blocks_before_start": {},
        "configured_pair": "BTC-USD",
        "position_count": None,
        "positions": [],
        "configured_symbol_side": None,
        "foreign_symbols": [],
        "recovery_reason": None,
        "worker_state": None,
        "in_flight_order_count": None,
        "in_flight_is_not_full_exchange_open_orders": True,
        "fill_count": None,
        "market_event_count": None,
        "market_event_names": [],
        "account_read": None,
        "place_blocked": False,
        "cancel_blocked": False,
        "leverage_blocked": False,
        "inner_place_calls": None,
        "error_type": None,
        "any_exchange_write": False,
    }
    if not credentials_supplied():
        return report

    cfg = WorkerConfig(mode="hyperliquid", execution_enabled=False, trading_pair="BTC-USD")
    runtime = build_runtime(cfg)
    inner = runtime.inner
    bridge = inner.connector
    raw = bridge.connector
    hb = getattr(raw, "_inner", raw)
    report["authenticated"] = bool(getattr(bridge, "authenticated", False))
    report["write_loops_disabled_before_start"] = bool(
        getattr(bridge, "write_loops_disabled", False) or getattr(hb, "_newhbot_write_loops_disabled", False)
    )
    report["trading_required"] = bool(getattr(hb, "is_trading_required", False))
    report["authenticator_present"] = getattr(hb, "authenticator", None) is not None

    blocks: dict[str, str] = {}
    for name in ("buy", "sell", "_place_order", "cancel", "set_leverage", "_execute_order_cancel"):
        try:
            result = getattr(raw, name)()
            if asyncio.iscoroutine(result):
                await result
            blocks[name] = "NOT_BLOCKED"
            report["any_exchange_write"] = True
        except ReadOnlyViolation:
            blocks[name] = "ReadOnlyViolation"
        except Exception as exc:
            blocks[name] = type(exc).__name__
    report["guard_blocks_before_start"] = blocks
    if not report["write_loops_disabled_before_start"]:
        report["error_type"] = "WriteLoopsNotDisabled"
        report["account_connection"] = "BLOCKED"
        return report
    if any(v == "NOT_BLOCKED" for v in blocks.values()):
        report["error_type"] = "WritePathNotBlocked"
        report["account_connection"] = "BLOCKED"
        return report

    try:
        await inner.connect()
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        report["account_connection"] = "BLOCKED"
        return report

    report["account_read"] = getattr(bridge, "account_read", None)
    report["user_stream_task"] = bool(getattr(bridge, "has_user_stream", False))
    init = getattr(hb, "_is_user_stream_initialized", None)
    try:
        report["user_stream_initialized"] = bool(init()) if callable(init) else None
    except Exception:
        report["user_stream_initialized"] = None
    report["ws_connected"] = bool(getattr(bridge, "ws_connected", False))
    await asyncio.sleep(5)
    try:
        report["user_stream_initialized"] = bool(init()) if callable(init) else None
    except Exception:
        report["user_stream_initialized"] = None
    listener = getattr(hb, "_user_stream_event_listener_task", None)
    tracker_task = getattr(hb, "_user_stream_tracker_task", None)
    report["user_stream_task"] = bool(listener is not None or getattr(bridge, "has_user_stream", False))
    report["user_stream_tracker_task"] = tracker_task is not None and not getattr(tracker_task, "done", lambda: True)()
    report["user_stream_listener_done"] = None if listener is None else bool(getattr(listener, "done", lambda: False)())
    report["recovery_reason"] = getattr(inner, "recovery_reason", None)
    report["foreign_symbols"] = list(getattr(inner, "foreign_symbols", []) or [])
    report["worker_state"] = inner.worker_state().value

    positions = await inner.get_positions()
    report["position_count"] = len(positions)
    report["positions"] = [_pos_row(item) for item in positions]
    configured = await inner.get_position("BTC-USD")
    report["configured_symbol_side"] = _side(configured)
    if configured.side != PositionSide.FLAT:
        report["configured_symbol"] = _pos_row(configured)

    tracker = getattr(hb, "in_flight_orders", None) or {}
    report["in_flight_order_count"] = len(tracker) if hasattr(tracker, "__len__") else None
    adapter_orders = await inner.get_open_orders()
    report["adapter_open_order_count"] = len(adapter_orders)
    fills = await inner.get_fills()
    report["fill_count"] = len(fills)
    events = list(bridge.recent_events()) if callable(getattr(bridge, "recent_events", None)) else []
    report["market_event_count"] = len(events)
    report["market_event_names"] = [str(item.get("event_name") or item.get("type")) for item in events]

    placed = await inner.place_order(
        PlaceOrderRequest(
            request_id="step4-readonly",
            cloid="0x" + "d" * 32,
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
            reduce_only=False,
        )
    )
    status = getattr(placed.status, "value", str(placed.status))
    report["place_blocked"] = status in {"REJECTED", "rejected"}
    err = str(placed.error or "")
    report["place_error_is_readonly"] = "read-only" in err or "execution disabled" in err
    report["place_rejected_before_connector"] = report["place_blocked"] and int(getattr(bridge, "place_calls", 0) or 0) == 0
    try:
        await inner.cancel_order("0x" + "d" * 32, "step4-readonly")
        report["cancel_blocked"] = False
        report["any_exchange_write"] = True
    except (ReadOnlyViolation, ExecutionDisabled):
        report["cancel_blocked"] = True
    try:
        await inner.set_leverage("BTC-USD", 2)
        report["leverage_blocked"] = False
        report["any_exchange_write"] = True
    except (ReadOnlyViolation, ExecutionDisabled):
        report["leverage_blocked"] = True
    report["inner_place_calls"] = int(getattr(bridge, "place_calls", 0) or 0)
    try:
        await inner.disconnect()
    except Exception:
        pass

    if report["account_read"] == "authenticated" and report["error_type"] is None:
        report["account_connection"] = "VERIFIED"
    elif report["error_type"]:
        report["account_connection"] = "BLOCKED"
    else:
        report["account_connection"] = "NOT VERIFIED"
    return report


def main() -> int:
    report = asyncio.run(_run())
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
