from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal

HUMMINGBOT_VERSION = "v2.16.0"
MIN_NOTIONAL_SIZE = Decimal("10")
DEFAULT_MARKET_SLIPPAGE = Decimal("0.05")
HYPERLIQUID_TESTNET_DOMAIN = "hyperliquid_perpetual_testnet"
HYPERLIQUID_MAINNET_DOMAIN = "hyperliquid_perpetual"
HYPERLIQUID_DOMAINS = frozenset({HYPERLIQUID_TESTNET_DOMAIN, HYPERLIQUID_MAINNET_DOMAIN})
HYPERLIQUID_INFO_URLS = {
    HYPERLIQUID_TESTNET_DOMAIN: "https://api.hyperliquid-testnet.xyz/info",
    HYPERLIQUID_MAINNET_DOMAIN: "https://api.hyperliquid.xyz/info",
}


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
    hyperliquid_domain: str = HYPERLIQUID_TESTNET_DOMAIN
    backend_heartbeat_timeout_seconds: float = 30.0

    @property
    def is_hyperliquid(self) -> bool:
        return self.mode == "hyperliquid"


def load_config() -> WorkerConfig:
    slippage_raw = os.environ.get("EXECUTION_SLIPPAGE", str(DEFAULT_MARKET_SLIPPAGE))
    leverage_raw = os.environ.get("EXECUTION_LEVERAGE", "1")
    domain = os.environ.get("HYPERLIQUID_DOMAIN", HYPERLIQUID_TESTNET_DOMAIN).strip().lower()
    if domain not in HYPERLIQUID_DOMAINS:
        raise RuntimeError(
            f"HYPERLIQUID_DOMAIN must be one of {sorted(HYPERLIQUID_DOMAINS)}"
        )
    return WorkerConfig(
        mode=os.environ.get("EXECUTION_MODE", "mock").strip().lower(),
        execution_enabled=_bool_env("EXECUTION_ENABLED", False),
        trading_pair=os.environ.get("EXECUTION_TRADING_PAIR", "BTC-USD").strip() or "BTC-USD",
        slippage=Decimal(slippage_raw),
        expected_leverage=int(leverage_raw),
        hummingbot_version=os.environ.get("HUMMINGBOT_VERSION", HUMMINGBOT_VERSION),
        use_live_connector=_bool_env("HUMMINGBOT_LIVE_CONNECTOR", False),
        hyperliquid_domain=domain,
        backend_heartbeat_timeout_seconds=float(
            os.environ.get("BACKEND_HEARTBEAT_TIMEOUT_SECONDS", "30")
        ),
    )
