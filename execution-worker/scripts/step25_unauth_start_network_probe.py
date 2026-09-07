"""STEP 2.5: trading_required=True without credentials.

If start_network / constructor requires a real Hyperliquid account, stop.
Never supply keys. Never send orders.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import traceback


async def main() -> dict:
    report: dict = {
        "constructor": None,
        "authenticator_is_none": None,
        "start_network": None,
        "user_stream_started": None,
        "status_polling_started": None,
        "stop_network": None,
        "blocked_reason": None,
        "error": None,
    }
    try:
        from hummingbot.connector.derivative.hyperliquid_perpetual.hyperliquid_perpetual_derivative import (
            HyperliquidPerpetualDerivative,
        )

        init_src = inspect.getsource(HyperliquidPerpetualDerivative.__init__)
        report["init_sets_authenticator_when_trading_required"] = "trading_required" in init_src
        try:
            connector = HyperliquidPerpetualDerivative(
                trading_required=True,
                trading_pairs=["BTC-USD"],
                hyperliquid_perpetual_secret_key=None,
                hyperliquid_perpetual_address=None,
            )
            report["constructor"] = "ok"
        except Exception as exc:
            report["constructor"] = f"{type(exc).__name__}: {exc}"
            report["blocked_reason"] = "requires authenticated Hyperliquid runtime"
            return report

        report["authenticator_is_none"] = connector.authenticator is None
        if connector.authenticator is not None:
            report["blocked_reason"] = "requires authenticated Hyperliquid runtime"
            report["start_network"] = "not_started — authenticator present without user-supplied keys; refusing to continue"
            return report

        # Authenticator is None even with trading_required=True. Probe start_network
        # but abort if a user stream or status poll starts (those are account paths).
        try:
            await asyncio.wait_for(connector.start_network(), timeout=20)
            report["start_network"] = "returned"
            report["user_stream_started"] = connector._user_stream_tracker_task is not None
            report["status_polling_started"] = connector._status_polling_task is not None
            if report["user_stream_started"] or report["status_polling_started"]:
                report["blocked_reason"] = "requires authenticated Hyperliquid runtime"
                await asyncio.wait_for(connector.stop_network(), timeout=10)
                report["stop_network"] = "stopped_after_account_path_detected"
                return report
            await asyncio.wait_for(connector.stop_network(), timeout=10)
            report["stop_network"] = "ok"
        except Exception as exc:
            report["start_network"] = f"{type(exc).__name__}: {exc}"
            report["blocked_reason"] = "requires authenticated Hyperliquid runtime"
            try:
                await asyncio.wait_for(connector.stop_network(), timeout=10)
                report["stop_network"] = "ok-after-error"
            except Exception as stop_exc:
                report["stop_network"] = f"{type(stop_exc).__name__}: {stop_exc}"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
        report["blocked_reason"] = report["blocked_reason"] or "requires authenticated Hyperliquid runtime"
    return report


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), indent=2, default=str))
