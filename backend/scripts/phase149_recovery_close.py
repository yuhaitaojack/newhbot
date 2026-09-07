"""Reconcile and safely close any residual live position through the Controller."""

from __future__ import annotations

import asyncio
import json
import os

from app.core.config import get_settings
from app.core.enums import PositionSide, SignalType, SystemState
from app.execution.client import HttpExecutionClient
from app.main import create_app
from app.repositories import SettingsRepository


async def main() -> None:
    if os.environ.get("HYPERLIQUID_DOMAIN") != "hyperliquid_perpetual":
        raise RuntimeError("mainnet_domain_required")
    if os.environ.get("EXECUTION_ENABLED", "").lower() != "true":
        raise RuntimeError("live_execution_required")

    settings = get_settings()
    execution = HttpExecutionClient(
        settings.execution_worker_url,
        timeout=settings.execution_worker_write_timeout_seconds,
        read_timeout=settings.execution_worker_read_timeout_seconds,
    )
    app = create_app(settings=settings, execution=execution, bootstrap_schema=True)
    async with app.router.lifespan_context(app):
        before = None
        last_error = None
        for _ in range(12):
            try:
                health = await execution.worker_status()
                before = await execution.get_position("BTC-USD")
                if health.get("ready") and before.side != PositionSide.FLAT:
                    break
            except Exception as exc:
                last_error = str(exc)
            await asyncio.sleep(3)
        if before is None:
            raise RuntimeError(f"position_query_failed:{last_error or 'unknown'}")
        if before.side == PositionSide.FLAT:
            orders = await execution.get_open_orders("BTC-USD")
            if orders:
                raise RuntimeError("flat_but_open_orders_present")
            print(json.dumps({"status": "confirmed_flat", "open_orders": []}), flush=True)
            return

        async with app.state.container.session_factory() as session:
            row = await SettingsRepository(session).get()
            row.trading_enabled = False
            row.system_state = SystemState.STOPPED.value
            row.estop = False
            row.leverage = 1
            await session.commit()
            started = await app.state.container.controller.start(session)
            if not started.get("ok"):
                raise RuntimeError(f"controller_start_failed:{started.get('reason')}")
            closed = await app.state.container.controller.handle_signal(
                session, SignalType.CLOSE, actor="phase149_recovery_close"
            )
            after = await execution.get_position("BTC-USD")
            print(
                json.dumps(
                    {
                        "before": before.model_dump(mode="json"),
                        "close": closed,
                        "after": after.model_dump(mode="json"),
                    },
                    default=str,
                ),
                flush=True,
            )
            if not closed.get("ok") or after.side != PositionSide.FLAT:
                raise RuntimeError("close_not_confirmed_flat")
            await app.state.container.controller.stop(session)


if __name__ == "__main__":
    asyncio.run(main())
