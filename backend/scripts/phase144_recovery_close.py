"""Emergency cleanup for the confirmed Phase 144 residual position."""

from __future__ import annotations

import asyncio
import json
import os

from app.core.config import get_settings
from app.core.enums import PositionSide, SystemState, SignalType
from app.execution.client import HttpExecutionClient
from app.main import create_app
from app.repositories import SettingsRepository


async def main() -> None:
    if os.environ.get("HYPERLIQUID_DOMAIN") != "hyperliquid_perpetual":
        raise RuntimeError("mainnet_domain_required")
    settings = get_settings()
    execution = HttpExecutionClient(
        settings.execution_worker_url,
        timeout=settings.execution_worker_write_timeout_seconds,
        read_timeout=settings.execution_worker_read_timeout_seconds,
    )
    app = create_app(settings=settings, execution=execution, bootstrap_schema=True)
    async with app.router.lifespan_context(app):
        container = app.state.container
        async with container.session_factory() as session:
            row = await SettingsRepository(session).get()
            row.trading_enabled = False
            row.system_state = SystemState.STOPPED.value
            row.estop = False
            row.leverage = 1
            await session.commit()
            before = await execution.get_position("BTC-USD")
            if before.side == PositionSide.FLAT:
                print(json.dumps({"status": "already_flat"}), flush=True)
                return
            started = await container.controller.start(session)
            print(json.dumps({"start": started, "before": before.model_dump(mode="json")}), flush=True)
            if not started.get("ok"):
                raise RuntimeError(f"controller_start_failed:{started.get('reason')}")
            closed = await container.controller.handle_signal(session, SignalType.CLOSE, actor="phase144_recovery_close")
            after = await execution.get_position("BTC-USD")
            print(json.dumps({"close": closed, "after": after.model_dump(mode="json")}), flush=True)
            if not closed.get("ok") or after.side != PositionSide.FLAT:
                raise RuntimeError("close_not_confirmed_flat")
            stopped = await container.controller.stop(session)
            print(json.dumps({"stop": stopped}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
