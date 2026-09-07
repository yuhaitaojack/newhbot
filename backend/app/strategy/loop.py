from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers.trading_controller import TradingController
from app.events.hub import EventHub
from app.execution.protocol import ExecutionClient
from app.repositories import AuditRepository, SettingsRepository, StrategyRepository
from app.strategy.runtime import StrategyRuntime
from app.repositories import effective_parameter_value

logger = logging.getLogger(__name__)


class StrategyLoop:
    """Explicitly supervised strategy loop. Construction never starts it."""

    def __init__(self, *, session_factory, execution: ExecutionClient, runtime: StrategyRuntime,
                 controller: TradingController, hub: EventHub, poll_seconds: float = 5.0) -> None:
        self._session_factory = session_factory
        self._execution = execution
        self._runtime = runtime
        self._controller = controller
        self._hub = hub
        self._poll_seconds = poll_seconds
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.last_error: str | None = None
        self.last_candle_timestamp: int | None = None
        self._await_new_candle = False

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> dict:
        if self.running:
            return {"ok": True, "running": True, "already_running": True}
        self._stop = asyncio.Event()
        self.last_error = None
        self._await_new_candle = True
        self._task = asyncio.create_task(self._run(), name="strategy-loop")
        return {"ok": True, "running": True}

    async def stop(self) -> dict:
        task = self._task
        if task is None:
            return {"ok": True, "running": False, "already_stopped": True}
        self._stop.set()
        await task
        self._task = None
        return {"ok": True, "running": False}

    async def close(self) -> None:
        if self.running:
            await self.stop()

    async def _stop_in_recovery(self, session: AsyncSession, reason: str) -> bool:
        self.last_error = reason
        await self._controller.enter_recovery(session, reason)
        return False

    async def _run(self) -> None:
        # Let the control request that started this task finish its DB transaction
        # before the first background session is opened. This also keeps startup
        # recovery and the first-candle warmup in a separate transaction boundary.
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)
            return
        except asyncio.TimeoutError:
            pass
        while not self._stop.is_set():
            try:
                keep_running = await self._tick()
                if keep_running is False:
                    self._task = None
                    return
                # A clean tick clears a previous transient error. Recovery
                # exits return False and set their reason explicitly, so that
                # the control plane can explain why the loop stopped.
                self.last_error = None
            except Exception as exc:
                logger.exception("strategy loop tick failed")
                reason = f"strategy_loop_failed:{type(exc).__name__}"
                try:
                    async with self._session_factory() as recovery_session:
                        await self._stop_in_recovery(recovery_session, reason)
                except Exception as recovery_exc:
                    self.last_error = f"strategy_loop_recovery_failed:{type(recovery_exc).__name__}"
                    logger.exception("strategy loop recovery failed")
                self._task = None
                return
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> bool:
        async with self._session_factory() as session:
            settings = await SettingsRepository(session).get()
            if not settings.trading_enabled or settings.system_state != "RUNNING":
                if settings.system_state != "RUNNING":
                    self.last_error = f"system_not_running:{settings.system_state}"
                    return False
                return True
            versions = await StrategyRepository(session).list_versions()
            version = next((item for item in versions if item.name == settings.active_strategy and item.version == settings.active_strategy_version), None)
            if version is None:
                raise ValueError("active strategy version is unavailable")
            manifest = json.loads(version.manifest_json or "{}")
            interval = str(manifest.get("interval", "5m"))
            try:
                worker = await self._execution.worker_status()
            except Exception as exc:
                return await self._stop_in_recovery(
                    session, f"worker_status_query_failed:{type(exc).__name__}"
                )
            if not bool(worker.get("ready")) or worker.get("worker_state") != "READY":
                try:
                    await self._execution.connect()
                except Exception as exc:
                    reason = f"worker_recovery_attempt_failed:{type(exc).__name__}"
                    return await self._stop_in_recovery(session, reason)
                try:
                    worker = await self._execution.worker_status()
                except Exception as exc:
                    return await self._stop_in_recovery(
                        session, f"worker_status_query_failed:{type(exc).__name__}"
                    )
            if not bool(worker.get("ready")) or worker.get("worker_state") != "READY":
                reason = f"worker_not_ready:{worker.get('worker_state', 'NOT_READY')}"
                return await self._stop_in_recovery(session, reason)
            try:
                bars = await self._execution.get_candles(settings.trading_pair, interval, 200)
            except Exception as exc:
                return await self._stop_in_recovery(
                    session, f"candle_query_failed:{type(exc).__name__}"
                )
            if not bars:
                return True
            timestamp = int(bars[-1].get("timestamp", bars[-1].get("t", 0)))
            if self._await_new_candle:
                self.last_candle_timestamp = timestamp or None
                self._await_new_candle = False
                return True
            if timestamp and timestamp == self.last_candle_timestamp:
                return True
            self.last_candle_timestamp = timestamp or None
            try:
                position = await self._execution.get_position(settings.trading_pair)
            except Exception as exc:
                return await self._stop_in_recovery(
                    session, f"position_query_failed:{type(exc).__name__}"
                )
            from app.core.enums import PositionSide
            if position.side == PositionSide.UNKNOWN:
                return await self._stop_in_recovery(session, "position_unknown")
            params = await StrategyRepository(session).parameters_for(version.id)
            snapshot = {
                "symbol": settings.trading_pair,
                "interval": interval,
                "bars": bars,
                "position_side": position.side.value,
                "entry_price": str(position.entry_price) if position.entry_price is not None else None,
                "parameters": {item.name: effective_parameter_value(item) for item in params},
            }
            try:
                evaluated = await self._runtime.evaluate(version.path, snapshot)
                from app.core.enums import SignalType
                signal = SignalType(evaluated["signal"])
            except Exception as exc:
                return await self._stop_in_recovery(
                    session, f"strategy_evaluation_failed:{type(exc).__name__}"
                )
            result = await self._controller.handle_signal(session, signal, actor="strategy_loop")
            await AuditRepository(session).add(
                "strategy_loop_tick",
                json.dumps({"strategy": version.name, "version": version.version, "timestamp": timestamp,
                            "signal": signal.value, "accepted": result.get("accepted", False)}),
                actor="strategy_loop",
            )
            await session.commit()
            return True
