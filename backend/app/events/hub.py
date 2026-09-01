from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any


class EventHub:
    """In-process fan-out for WebSocket clients."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    async def publish(self, event_type: str, payload: dict[str, Any], event_id: int | None = None) -> None:
        message = {"type": event_type, "payload": payload, "event_id": event_id}
        stale: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in self._subscribers:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                stale.append(queue)
        for queue in stale:
            self.unsubscribe(queue)

    async def stream(self, queue: asyncio.Queue[dict[str, Any]]) -> AsyncIterator[str]:
        while True:
            message = await queue.get()
            yield json.dumps(message, default=str)
