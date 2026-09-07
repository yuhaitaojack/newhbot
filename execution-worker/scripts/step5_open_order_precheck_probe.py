"""Read-only open-order precheck probe. EXECUTION_ENABLED must stay false.

Never prints secrets, private keys, or addresses.
Never calls place / cancel / set_leverage / buy / sell.
Does not persist orders. Does not call get_balance (funds are not re-certified here).
"""

from __future__ import annotations

import asyncio
import json
import sys


async def _run() -> dict:
    from app.config import WorkerConfig
    from app.factory import build_runtime
    from app.open_order_precheck import snapshot_open_orders
    from app.readonly_guard import ReadOnlyViolation

    report: dict = {
        "credentials_supplied": False,
        "execution_enabled": False,
        "authenticated": False,
        "account_read": None,
        "worker_state": None,
        "recovery_reason": None,
        "configured_side": None,
        "foreign_symbols": [],
        "open_order_precheck": None,
        "bridge_armed": None,
        "write_loops_disabled": False,
        "guard_blocks": {},
        "error_type": None,
        "account_connection": "BLOCKED",
    }
    from app.hummingbot_readonly import credentials_supplied

    report["credentials_supplied"] = credentials_supplied()
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
    guard = getattr(bridge, "connector", None)
    blocks: dict[str, str] = {}
    for name in ("buy", "sell", "_place_order", "cancel", "set_leverage"):
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
        return report
    report["account_read"] = getattr(bridge, "account_read", None)
    report["worker_state"] = inner.worker_state().value
    report["recovery_reason"] = getattr(inner, "recovery_reason", None)
    report["foreign_symbols"] = list(getattr(inner, "foreign_symbols", []) or [])
    try:
        pos = await inner.get_position("BTC-USD")
        report["configured_side"] = str(pos.side.value if hasattr(pos.side, "value") else pos.side)
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        report["configured_side"] = "UNKNOWN"
        return report
    report["open_order_precheck"] = await snapshot_open_orders(raw, configured_pair="BTC-USD")
    try:
        await inner.disconnect()
    except Exception:
        pass
    if report["account_read"] == "authenticated" and report["worker_state"] == "READY":
        report["account_connection"] = "VERIFIED"
    return report


def main() -> int:
    print(json.dumps(asyncio.run(_run())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
