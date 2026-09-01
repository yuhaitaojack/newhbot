from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal

HUMMINGBOT_VERSION = "v2.16.0"
MIN_NOTIONAL_SIZE = Decimal("10")
DEFAULT_MARKET_SLIPPAGE = Decimal("0.05")


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class WorkerConfig:
    """Process config. Keys must never be committed. Execution is disabled by default."""

    mode: str = "mock"
    execution_enabled: bool = False
    trading_pair: str = "BTC-USD"
    slippage: Decimal = DEFAULT_MARKET_SLIPPAGE
    expected_leverage: int = 1
    hummingbot_version: str = HUMMINGBOT_VERSION
    use_live_connector: bool = False

    @property
    def is_hyperliquid(self) -> bool:
        return self.mode == "hyperliquid"


def load_config() -> WorkerConfig:
    slippage_raw = os.environ.get("EXECUTION_SLIPPAGE", str(DEFAULT_MARKET_SLIPPAGE))
    leverage_raw = os.environ.get("EXECUTION_LEVERAGE", "1")
    return WorkerConfig(
        mode=os.environ.get("EXECUTION_MODE", "mock").strip().lower(),
        execution_enabled=_bool_env("EXECUTION_ENABLED", False),
        trading_pair=os.environ.get("EXECUTION_TRADING_PAIR", "BTC-USD").strip() or "BTC-USD",
        slippage=Decimal(slippage_raw),
        expected_leverage=int(leverage_raw),
        hummingbot_version=os.environ.get("HUMMINGBOT_VERSION", HUMMINGBOT_VERSION),
        use_live_connector=_bool_env("HUMMINGBOT_LIVE_CONNECTOR", False),
    )
