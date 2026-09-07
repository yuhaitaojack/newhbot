from __future__ import annotations

from app.config import HYPERLIQUID_DOMAINS, WorkerConfig, load_config
from app.hummingbot_readonly import (
    ReadOnlyHummingbotBridge,
    disable_exchange_write_loops,
    instantiate_authenticated,
    instantiate_readonly,
    load_account_credentials,
    try_load_hummingbot_connector_class,
)
from app.hyperliquid_adapter import HyperliquidExecutionAdapter
from app.mock_adapter import MockExecutionAdapter
from app.runtime import WorkerRuntime


def build_runtime(config: WorkerConfig | None = None) -> WorkerRuntime:
    config = config or load_config()
    if config.mode == "hyperliquid":
        if config.hyperliquid_domain not in HYPERLIQUID_DOMAINS:
            raise RuntimeError("unsupported Hyperliquid domain")
        if config.execution_enabled and load_account_credentials() is None:
            raise RuntimeError("EXECUTION_ENABLED requires authenticated Hyperliquid credentials")
        cls = try_load_hummingbot_connector_class()
        if cls is None:
            raise RuntimeError(
                "EXECUTION_MODE=hyperliquid requires hummingbot v2.16.0 in this runtime (official Worker image)"
            )
        creds = load_account_credentials()
        if creds is not None:
            secret_key, address = creds
            raw = instantiate_authenticated(
                cls,
                [config.trading_pair],
                secret_key=secret_key,
                address=address,
                domain=config.hyperliquid_domain,
            )
            disable_exchange_write_loops(raw)
            bridge = ReadOnlyHummingbotBridge(
                raw, authenticated=True, execution_enabled=config.execution_enabled
            )
        else:
            raw = instantiate_readonly(cls, [config.trading_pair], domain=config.hyperliquid_domain)
            disable_exchange_write_loops(raw)
            bridge = ReadOnlyHummingbotBridge(raw, execution_enabled=False)
        inner = HyperliquidExecutionAdapter(config, bridge)
    else:
        inner = MockExecutionAdapter()
    return WorkerRuntime(inner, config)
