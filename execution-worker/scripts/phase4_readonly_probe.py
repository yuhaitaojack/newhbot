"""PHASE 4 read-only probe. Run inside hummingbot/hummingbot:version-2.16.0.

Never calls buy/sell/_place_order/cancel/updateLeverage/set_leverage.
Never prints secrets. Account reads that need a user address are skipped.
"""

from __future__ import annotations

import inspect
import json
import sys
import traceback


FORBIDDEN = (
    "buy",
    "sell",
    "_place_order",
    "place_order",
    "cancel",
    "_place_cancel",
    "updateLeverage",
    "set_leverage",
    "_set_trading_pair_leverage",
)


def main() -> int:
    report: dict = {
        "python": sys.version,
        "python_major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        "import_ok": False,
        "instantiate_ok": False,
        "trading_required": None,
        "authenticator_is_none": None,
        "supported_position_modes": None,
        "oneway_present": None,
        "hedge_present": None,
        "forbidden_called": [],
        "error": None,
    }
    try:
        from hummingbot.connector.derivative.hyperliquid_perpetual.hyperliquid_perpetual_derivative import (
            HyperliquidPerpetualDerivative,
        )

        report["import_ok"] = True
        from hummingbot.core.data_type.common import PositionMode
        report["class_name"] = HyperliquidPerpetualDerivative.__name__
        params = inspect.signature(HyperliquidPerpetualDerivative.__init__).parameters
        report["constructor_params"] = list(params)
        report["has_trading_required"] = "trading_required" in params

        connector = HyperliquidPerpetualDerivative(
            trading_required=False,
            trading_pairs=["BTC-USD"],
            hyperliquid_perpetual_secret_key=None,
            hyperliquid_perpetual_address=None,
        )
        report["instantiate_ok"] = True
        report["trading_required"] = bool(connector.is_trading_required)
        report["authenticator_is_none"] = connector.authenticator is None
        modes = [str(item) for item in connector.supported_position_modes()]
        report["supported_position_modes"] = modes
        report["oneway_present"] = any("ONEWAY" in item.upper() or item.endswith(".ONEWAY") for item in modes) or (
            PositionMode.ONEWAY in connector.supported_position_modes()
        )
        report["hedge_present"] = any("HEDGE" in item.upper() for item in modes)
        report["forbidden_methods_present"] = [name for name in FORBIDDEN if hasattr(connector, name)]
        report["forbidden_called"] = []
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
        print(json.dumps(report, indent=2, default=str))
        return 1
    print(json.dumps(report, indent=2, default=str))
    if report["trading_required"] or not report["authenticator_is_none"]:
        return 2
    if not report["oneway_present"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
