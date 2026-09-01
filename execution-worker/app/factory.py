from __future__ import annotations

from app.config import WorkerConfig, load_config
from app.connector_bridge import FakeConnector, try_load_hummingbot_connector_class
from app.hummingbot_readonly import ReadOnlyHummingbotBridge, instantiate_readonly
from app.hyperliquid_adapter import HyperliquidExecutionAdapter
from app.mock_adapter import MockExecutionAdapter
from app.runtime import WorkerRuntime


def build_runtime(config: WorkerConfig | None = None) -> WorkerRuntime:
    config = config or load_config()
    if config.mode == "hyperliquid":
        if config.use_live_connector:
            if config.execution_enabled:
                raise RuntimeError("PHASE 4 forbids EXECUTION_ENABLED with a live Hummingbot connector")
            cls = try_load_hummingbot_connector_class()
            if cls is None:
                raise RuntimeError("HUMMINGBOT_LIVE_CONNECTOR set but hummingbot v2.16.0 is not importable")
            raw = instantiate_readonly(cls, [config.trading_pair])
            inner = HyperliquidExecutionAdapter(config, ReadOnlyHummingbotBridge(raw))
        else:
            inner = HyperliquidExecutionAdapter(config, FakeConnector())
    else:
        inner = MockExecutionAdapter()
    return WorkerRuntime(inner, config)
