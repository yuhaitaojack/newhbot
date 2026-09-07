"""STEP 4: inspect v2.16.0 start_network write loops. Never places or cancels."""

from __future__ import annotations

import inspect
import json
import sys


def main() -> int:
    report: dict = {
        "import_ok": False,
        "lost_orders_loop_in_start_network": False,
        "lost_orders_gated_by_trading_required": False,
        "cancel_lost_orders_calls_execute_cancel": False,
        "user_stream_gated_by_trading_required": False,
        "status_polling_gated_by_trading_required": False,
        "error": None,
    }
    try:
        from hummingbot.connector.exchange_py_base import ExchangePyBase

        report["import_ok"] = True
        start_src = inspect.getsource(ExchangePyBase.start_network)
        report["lost_orders_loop_in_start_network"] = "_lost_orders_update_polling_loop" in start_src
        report["lost_orders_gated_by_trading_required"] = "if self.is_trading_required" in start_src
        report["user_stream_gated_by_trading_required"] = "_user_stream_event_listener" in start_src
        report["status_polling_gated_by_trading_required"] = "_status_polling_loop" in start_src
        cancel_src = inspect.getsource(ExchangePyBase._cancel_lost_orders)
        report["cancel_lost_orders_calls_execute_cancel"] = "_execute_order_cancel" in cancel_src
        report["start_network_excerpt_has_write_risk"] = (
            report["lost_orders_loop_in_start_network"]
            and report["cancel_lost_orders_calls_execute_cancel"]
        )
    except Exception as exc:
        report["error"] = type(exc).__name__
        print(json.dumps(report))
        return 1
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
