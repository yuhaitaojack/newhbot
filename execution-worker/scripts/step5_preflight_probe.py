"""STEP 5 PRE-FLIGHT query-only probe. EXECUTION_ENABLED must stay false.

Never prints secrets, private keys, or addresses.
Never calls place / cancel / set_leverage / buy / sell.
"""

from __future__ import annotations

import asyncio
import json
import sys


async def _run() -> dict:
    from app.config import WorkerConfig
    from app.factory import build_runtime
    from app.hummingbot_readonly import credentials_supplied
    from app.readonly_guard import ReadOnlyViolation

    report: dict = {
        "credentials_supplied": credentials_supplied(),
        "execution_enabled": False,
        "authenticated": False,
        "account_read": None,
        "worker_state": None,
        "recovery_reason": None,
        "one_way_ok": None,
        "configured_pair": "BTC-USD",
        "configured_side": None,
        "configured_size": None,
        "foreign_symbols": [],
        "position_symbols": [],
        "equity": None,
        "available": None,
        "tick_size": None,
        "step_size": None,
        "min_order_size": None,
        "min_notional": None,
        "open_order_count": None,
        "open_order_source": "hummingbot_in_flight_tracker",
        "exchange_wide_open_orders": "NOT VERIFIED",
        "in_flight_is_not_full_book": True,
        "funds_check": "FAIL",
        "balance_query": None,
        "write_loops_disabled": False,
        "guard_blocks": {},
        "saved_original_place": False,
        "bridge_armed": None,
        "open_order_precheck": None,
        "error_type": None,
        "account_connection": "BLOCKED",
    }
    if not credentials_supplied():
        return report

    cfg = WorkerConfig(mode="hyperliquid", execution_enabled=False, trading_pair="BTC-USD")
    runtime = build_runtime(cfg)
    inner = runtime.inner
    bridge = inner.connector
    report["execution_enabled"] = bool(runtime.config.execution_enabled)
    report["authenticated"] = bool(getattr(bridge, "authenticated", False))
    report["bridge_armed"] = bool(getattr(bridge, "execution_enabled", False))
    report["write_loops_disabled"] = bool(getattr(bridge, "write_loops_disabled", False))
    raw = getattr(bridge, "_inner", lambda: None)()
    report["saved_original_place"] = callable(getattr(raw, "_newhbot_original_place_order", None))
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
        lost = getattr(raw, "_cancel_lost_orders", None)
        if callable(lost):
            maybe = lost()
            if asyncio.iscoroutine(maybe):
                await maybe
        report["lost_order_cancel_noop"] = True
    except Exception as exc:
        report["lost_order_cancel_noop"] = False
        report["lost_order_error"] = type(exc).__name__

    try:
        await inner.connect()
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        return report

    report["account_read"] = getattr(bridge, "account_read", None)
    report["worker_state"] = inner.worker_state().value
    report["recovery_reason"] = getattr(inner, "recovery_reason", None)
    report["one_way_ok"] = bool(getattr(inner, "one_way_ok", False))
    report["foreign_symbols"] = list(getattr(inner, "foreign_symbols", []) or [])
    try:
        pos = await inner.get_position("BTC-USD")
        report["configured_side"] = str(pos.side.value if hasattr(pos.side, "value") else pos.side)
        report["configured_size"] = str(pos.size)
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        report["configured_side"] = "UNKNOWN"
        return report
    positions = await inner.get_positions()
    report["position_symbols"] = [str(item.symbol) for item in positions]
    try:
        bal = await inner.get_balance()
        report["equity"] = str(bal.equity)
        report["available"] = str(bal.available)
        report["margin_used"] = str(bal.margin_used)
        report["balance_query"] = "authenticated"
    except Exception as exc:
        report["balance_query"] = type(exc).__name__
        report["equity"] = None
        report["available"] = None
        report["funds_check"] = "FAIL"
    refresh_rules = getattr(raw, "_update_trading_rules", None)
    if callable(refresh_rules):
        try:
            maybe = refresh_rules()
            if asyncio.iscoroutine(maybe):
                await asyncio.wait_for(maybe, timeout=30)
            report["trading_rules_refreshed"] = True
        except Exception as exc:
            report["trading_rules_refresh_error"] = type(exc).__name__
    live_rules = getattr(getattr(bridge, "connector", None), "trading_rules", None) or {}
    report["trading_rules_count"] = len(live_rules)
    report["btc_usd_rule_present"] = "BTC-USD" in live_rules
    try:
        rule = bridge.trading_rule("BTC-USD")
        report["tick_size"] = str(rule.tick_size)
        report["step_size"] = str(rule.step_size)
        report["min_order_size"] = str(rule.min_order_size)
        report["min_notional"] = str(rule.min_notional)
    except Exception as exc:
        report["trading_rule_error"] = type(exc).__name__
    try:
        orders = await inner.get_open_orders("BTC-USD")
        report["open_order_count"] = len(orders)
        report["open_order_source"] = "hummingbot_in_flight_tracker"
        report["exchange_wide_open_orders"] = "NOT VERIFIED"
    except Exception as exc:
        report["open_order_error"] = type(exc).__name__
        report["exchange_wide_open_orders"] = "NOT VERIFIED"
    from app.open_order_precheck import snapshot_open_orders

    report["open_order_precheck"] = await snapshot_open_orders(raw, configured_pair="BTC-USD")
    precheck = report["open_order_precheck"] or {}
    if precheck.get("status") == "VERIFIED":
        report["exchange_wide_open_orders"] = "VERIFIED"
    try:
        await inner.disconnect()
    except Exception:
        pass
    if report["account_read"] == "authenticated" and report["worker_state"] == "READY":
        report["account_connection"] = "VERIFIED"
    elif report["account_read"] == "authenticated":
        report["account_connection"] = "NOT VERIFIED"
    min_notional = report.get("min_notional")
    available = report.get("available")
    if (
        report.get("balance_query") == "authenticated"
        and available is not None
        and min_notional is not None
    ):
        from decimal import Decimal

        report["funds_check"] = "PASS" if Decimal(str(available)) >= Decimal(str(min_notional)) else "FAIL"
    else:
        report["funds_check"] = "FAIL"
    return report


def main() -> int:
    print(json.dumps(asyncio.run(_run())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
