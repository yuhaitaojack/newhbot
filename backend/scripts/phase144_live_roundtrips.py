"""Run ten explicitly supervised Hyperliquid mainnet round trips.

This is an operator-invoked evidence harness, not a second execution path:
ema5break is evaluated in StrategyRuntime and every order goes through the
TradingController. It intentionally stops on the first unconfirmed result.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from decimal import Decimal

from app.core.config import get_settings
from app.core.enums import PositionSide, SignalType, SystemState
from app.execution.client import HttpExecutionClient
from app.main import create_app
from app.repositories import OrderRepository, SettingsRepository


PAIR = "BTC-USD"
STRATEGY_PATH = "/app/strategies/ema5break/strategy.py"


def _bars(base: float, direction: str) -> list[dict]:
    rows = []
    for _ in range(15):
        if direction == "LONG":
            rows.append({"open": base + 10, "high": base + 20, "low": base - 20, "close": base + 5})
        else:
            rows.append({"open": base - 10, "high": base + 20, "low": base - 20, "close": base - 5})
    if direction == "LONG":
        rows.extend([
            {"open": base + 10, "high": base + 20, "low": base - 20, "close": base + 5},
            {"open": base - 10, "high": base + 30, "low": base - 30, "close": base + 20},
        ])
    else:
        rows.extend([
            {"open": base - 10, "high": base + 20, "low": base - 20, "close": base - 5},
            {"open": base + 10, "high": base + 30, "low": base - 30, "close": base - 20},
        ])
    return rows


def _close_bars(entry: float, side: PositionSide) -> list[dict]:
    rows = [
        {"open": entry, "high": entry + 100, "low": entry - 100, "close": entry + 10}
        for _ in range(15)
    ]
    if side == PositionSide.LONG:
        rows.append({"open": entry, "high": entry + 2100, "low": entry - 50, "close": entry + 2000})
    else:
        rows.append({"open": entry, "high": entry + 50, "low": entry - 2100, "close": entry - 2000})
    return rows


async def _wait_position(execution, expected: PositionSide, timeout: float = 45.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = await execution.get_position(PAIR)
        if last.side == expected:
            return last
        await asyncio.sleep(1)
    raise RuntimeError(f"position_confirmation_timeout:{expected.value}:{getattr(last, 'side', None)}")


async def _preflight(execution, *, require_ready: bool = True):
    health = await execution.worker_status()
    position = await execution.get_position(PAIR)
    positions = await execution.get_positions()
    orders = await execution.get_open_orders()
    balance = await execution.get_balance()
    if require_ready and (not health.get("ready") or health.get("worker_state") != "READY"):
        raise RuntimeError(f"worker_not_ready:{health.get('worker_state')}")
    if position.side != PositionSide.FLAT:
        raise RuntimeError(f"not_flat:{position.side.value}:{position.size}")
    if any(item.side != PositionSide.FLAT for item in positions):
        raise RuntimeError("foreign_position_present")
    if orders:
        raise RuntimeError("open_orders_present")
    if balance.available < Decimal("10"):
        raise RuntimeError(f"insufficient_available:{balance.available}")
    return {
        "worker_state": health.get("worker_state"),
        "sync_status": health.get("sync_status"),
        "position": position.side.value,
        "available": str(balance.available),
        "open_orders": len(orders),
    }


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
    report = {"pair": PAIR, "strategy": "ema5break", "rounds": [], "status": "STOPPED"}

    async with app.router.lifespan_context(app):
        container = app.state.container
        async with container.session_factory() as session:
            row = await SettingsRepository(session).get()
            row.trading_enabled = False
            row.system_state = SystemState.STOPPED.value
            row.estop = False
            row.leverage = 1
            row.position_percentage = Decimal("70")
            row.order_type = "MARKET"
            await session.commit()
            report["preflight_before_start"] = await _preflight(execution, require_ready=False)
            started = await container.controller.start(session)
            report["start"] = started
            if not started.get("ok"):
                raise RuntimeError(f"controller_start_failed:{started.get('reason')}")

        for index in range(1, 11):
            direction = "LONG" if index <= 5 else "SHORT"
            async with container.session_factory() as session:
                settings_row = await SettingsRepository(session).get()
                market = await execution.get_market_data(PAIR)
                base = float(market["mid"])
                evaluated = await container.strategy_runtime.evaluate(
                    STRATEGY_PATH,
                    {
                        "symbol": PAIR,
                        "interval": "5m",
                        "bars": _bars(base, direction),
                        "position_side": PositionSide.FLAT.value,
                        "parameters": {"ema_period": 5, "atr_period": 14, "atr_stop_mult": 2.0, "tp_rr": 1.5},
                    },
                )
                signal = SignalType(evaluated["signal"])
                if signal.value != direction:
                    raise RuntimeError(f"strategy_signal_mismatch:{index}:{direction}:{signal.value}")
                opened = await container.controller.handle_signal(
                    session, signal, actor=f"phase144_ema5break_{direction.lower()}_{index}"
                )
                if not opened.get("accepted"):
                    raise RuntimeError(f"open_rejected:{index}:{opened}")
                live_open = await _wait_position(
                    execution, PositionSide.LONG if direction == "LONG" else PositionSide.SHORT
                )

                close_eval = await container.strategy_runtime.evaluate(
                    STRATEGY_PATH,
                    {
                        "symbol": PAIR,
                        "interval": "5m",
                        "bars": _close_bars(float(live_open.entry_price), live_open.side),
                        "position_side": live_open.side.value,
                        "entry_price": str(live_open.entry_price),
                        "parameters": {"ema_period": 5, "atr_period": 14, "atr_stop_mult": 2.0, "tp_rr": 1.5},
                    },
                )
                if close_eval["signal"] != SignalType.CLOSE.value:
                    raise RuntimeError(f"strategy_close_mismatch:{index}:{close_eval}")
                closed = await container.controller.handle_signal(session, SignalType.CLOSE, actor="strategy_loop")
                if not closed.get("ok"):
                    raise RuntimeError(f"close_failed:{index}:{closed}")
                await _wait_position(execution, PositionSide.FLAT)
                post = await _preflight(execution)
                report["rounds"].append(
                    {
                        "index": index,
                        "direction": direction,
                        "open_signal": signal.value,
                        "open": opened,
                        "entry_price": str(live_open.entry_price),
                        "close_signal": close_eval["signal"],
                        "close": closed,
                        "post_cycle": post,
                    }
                )
                print(json.dumps({"round": index, "direction": direction, "open": opened, "close": closed}, default=str), flush=True)

        async with container.session_factory() as session:
            stopped = await container.controller.stop(session)
            report["stop"] = stopped
        report["final_preflight"] = await _preflight(execution)
        report["status"] = "COMPLETE"
    print(json.dumps(report, indent=2, default=str), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
