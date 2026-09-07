"""Monitor real ema5break candles and complete five long/five short round trips."""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.core.config import get_settings
from app.core.enums import PositionSide, SignalType, SystemState
from app.execution.client import HttpExecutionClient
from app.main import create_app
from app.repositories import SettingsRepository


PAIR = "BTC-USD"
INTERVAL = "5m"
STRATEGY_PATH = "/app/strategies/ema5break/strategy.py"
REPORT_PATH = Path(os.environ.get("PHASE_REPORT_PATH", "/app/data/phase145_live_monitor_report.json"))
MONITOR_ACTOR = os.environ.get("PHASE_MONITOR_ACTOR", "ema5break_live_monitor")
CHECK_OFFSET_SECONDS = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save(report: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


def _seed_completed() -> dict[str, int]:
    raw = os.environ.get("PHASE_SEED_COMPLETED", "").strip()
    if not raw:
        return {"LONG": 0, "SHORT": 0}
    try:
        parsed = json.loads(raw)
        return {
            "LONG": max(0, min(5, int(parsed.get("LONG", 0)))),
            "SHORT": max(0, min(5, int(parsed.get("SHORT", 0)))),
        }
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("invalid_phase_seed_completed") from exc


def _closed_bars(bars: list[dict]) -> list[dict]:
    boundary = int(time.time() * 1000)
    boundary -= boundary % (5 * 60 * 1000)
    return [item for item in bars if int(item.get("timestamp", 0)) < boundary]


async def _wait_for_next_poll() -> None:
    """Keep the runner alive continuously; the strategy still keys off 5m bars."""
    await asyncio.sleep(5)


async def _wait_position(execution, expected: PositionSide, timeout: float = 45.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = await execution.get_position(PAIR)
        if last.side == expected:
            return last
        await asyncio.sleep(1)
    raise RuntimeError(f"position_confirmation_timeout:{expected.value}:{getattr(last, 'side', None)}")


async def _preflight(execution) -> dict:
    health = await execution.worker_status()
    position = await execution.get_position(PAIR)
    positions = await execution.get_positions()
    orders = await execution.get_open_orders()
    balance = await execution.get_balance()
    foreign = [
        item.model_dump(mode="json")
        for item in positions
        if item.side != PositionSide.FLAT and item.symbol != PAIR
    ]
    result = {
        "time": _now(),
        "health": health,
        "position": position.model_dump(mode="json"),
        "positions": [item.model_dump(mode="json") for item in positions],
        "open_orders": [item.model_dump(mode="json") for item in orders],
        "balance": balance.model_dump(mode="json"),
    }
    if position.side == PositionSide.UNKNOWN or foreign or orders:
        raise RuntimeError("preflight_not_reconciled_or_clean")
    # An existing configured position may have less than the opening minimum
    # available; it must still be allowed to resume and close safely.
    if position.side == PositionSide.FLAT and balance.available < Decimal("10"):
        raise RuntimeError(f"insufficient_available:{balance.available}")
    return result


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
    report = {
        "status": "RUNNING",
        "started_at": _now(),
        "pair": PAIR,
        "interval": INTERVAL,
        "strategy": "ema5break",
        "signal_source": "real_closed_hyperliquid_candles",
        "completed": _seed_completed(),
        "rounds": [],
        "issues": [],
        "observations": [],
    }

    async with app.router.lifespan_context(app):
        container = app.state.container
        try:
            report["preflight_before_start"] = await _preflight(execution)
            resumed_side = report["preflight_before_start"]["position"]["side"]
            if resumed_side in {PositionSide.LONG.value, PositionSide.SHORT.value}:
                report["rounds"].append(
                    {
                        "direction": resumed_side,
                        "resumed": True,
                        "entry_price": report["preflight_before_start"]["position"].get("entry_price"),
                        "opened_at": report["preflight_before_start"]["time"],
                    }
                )
            async with container.session_factory() as session:
                row = await SettingsRepository(session).get()
                row.trading_enabled = False
                row.system_state = SystemState.STOPPED.value
                row.estop = False
                row.leverage = 1
                # Leave enough headroom above Hyperliquid's $10 minimum after
                # the Worker rounds quantity down to the exchange step size.
                row.position_percentage = Decimal("75")
                row.order_type = "MARKET"
                await session.commit()
                started = await container.controller.start(session)
                report["start"] = started
                if not started.get("ok"):
                    raise RuntimeError(f"controller_start_failed:{started.get('reason')}")
            _save(report)
            print(json.dumps({"event": "STARTED", "completed": report["completed"]}), flush=True)

            last_candle = None
            while report["completed"]["LONG"] < 5 or report["completed"]["SHORT"] < 5:
                await _wait_for_next_poll()
                health = await execution.worker_status()
                if not health.get("ready") or health.get("worker_state") != "READY":
                    raise RuntimeError(f"worker_not_ready:{health.get('worker_state')}")
                bars = _closed_bars(await execution.get_candles(PAIR, INTERVAL, 200))
                if len(bars) < 20:
                    raise RuntimeError(f"too_few_closed_candles:{len(bars)}")
                candle = int(bars[-1]["timestamp"])
                if candle == last_candle:
                    continue
                last_candle = candle
                live = await execution.get_position(PAIR)
                snapshot = {
                    "symbol": PAIR,
                    "interval": INTERVAL,
                    "bars": bars,
                    "position_side": live.side.value,
                    "entry_price": str(live.entry_price) if live.entry_price is not None else None,
                    "parameters": {"ema_period": 5, "atr_period": 14, "atr_stop_mult": 2.0, "tp_rr": 1.5},
                }
                evaluated = await container.strategy_runtime.evaluate(STRATEGY_PATH, snapshot)
                signal = SignalType(evaluated["signal"])
                report["observations"].append(
                    {"time": _now(), "candle_timestamp": candle, "position": live.side.value, "signal": signal.value}
                )

                if live.side == PositionSide.FLAT and signal in {SignalType.LONG, SignalType.SHORT}:
                    direction = signal.value
                    if report["completed"][direction] >= 5:
                        report["observations"].append({"time": _now(), "event": "signal_skipped_quota", "signal": direction})
                    else:
                        async with container.session_factory() as session:
                            opened = await container.controller.handle_signal(session, signal, actor=MONITOR_ACTOR)
                        if not opened.get("accepted"):
                            raise RuntimeError(
                                f"open_rejected:{direction}:{opened.get('reason') or opened.get('status')}"
                            )
                        expected = PositionSide.LONG if direction == "LONG" else PositionSide.SHORT
                        confirmed = await _wait_position(execution, expected)
                        round_row = {
                            "direction": direction,
                            "signal_candle_timestamp": candle,
                            "signal": evaluated,
                            "open": opened,
                            "entry_price": str(confirmed.entry_price),
                            "opened_at": _now(),
                        }
                        report["rounds"].append(round_row)
                        _save(report)
                        print(json.dumps({"event": "OPEN_CONFIRMED", "direction": direction, "completed": report["completed"]}), flush=True)

                elif live.side in {PositionSide.LONG, PositionSide.SHORT} and signal == SignalType.CLOSE:
                    direction = live.side.value
                    async with container.session_factory() as session:
                        closed = await container.controller.handle_signal(session, SignalType.CLOSE, actor=MONITOR_ACTOR)
                    await _wait_position(execution, PositionSide.FLAT)
                    matching = next((item for item in reversed(report["rounds"]) if item.get("direction") == direction and "closed" not in item), None)
                    if matching is None:
                        raise RuntimeError("close_without_tracked_open")
                    matching["close_signal_candle_timestamp"] = candle
                    matching["close_signal"] = evaluated
                    matching["closed"] = closed
                    matching["closed_at"] = _now()
                    report["completed"][direction] += 1
                    _save(report)
                    print(json.dumps({"event": "CLOSE_CONFIRMED", "direction": direction, "completed": report["completed"]}), flush=True)

                _save(report)

            async with container.session_factory() as session:
                report["stop"] = await container.controller.stop(session)
            report["final_preflight"] = await _preflight(execution)
            report["status"] = "COMPLETE"
        except Exception as exc:
            issue = {"time": _now(), "type": type(exc).__name__, "message": str(exc)}
            report["issues"].append(issue)
            report["status"] = "STOPPED_RECOVERY"
            try:
                async with container.session_factory() as session:
                    await container.controller.enter_recovery(session, f"phase145_monitor:{type(exc).__name__}")
            except Exception as recovery_exc:
                report["issues"].append({"time": _now(), "type": type(recovery_exc).__name__, "message": "recovery_write_failed"})
            _save(report)
            print(json.dumps({"event": "STOPPED_RECOVERY", "issue": issue, "completed": report["completed"]}), flush=True)
            raise
        finally:
            _save(report)
    print(json.dumps(report, indent=2, default=str), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
