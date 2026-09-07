from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class WorkerHeartbeatService:
    def __init__(self, execution, interval_seconds: float = 5.0) -> None:
        self._execution = execution
        self._interval_seconds = max(float(interval_seconds), 1.0)
        self._task: asyncio.Task | None = None

    async def _send(self) -> None:
        heartbeat = getattr(self._execution, "heartbeat", None)
        if callable(heartbeat):
            await heartbeat()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        try:
            await self._send()
        except Exception:
            logger.exception("initial worker heartbeat failed")
        self._task = asyncio.create_task(self._run(), name="worker-heartbeat")

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._interval_seconds)
                await self._send()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("worker heartbeat failed")
