from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import SystemState
from app.core.logging import log_extra
from app.events.hub import EventHub
from app.execution.protocol import ExecutionClient
from app.repositories import EventRepository, OrderRepository, PositionRepository, SettingsRepository

logger = logging.getLogger(__name__)


class RecoveryManager:
    """PHASE 2 skeleton. Full scenario matrix is later. Recovery forbids opens via Guard."""

    def __init__(self, execution: ExecutionClient, hub: EventHub) -> None:
        self._execution = execution
        self._hub = hub

    async def bootstrap(self, session: AsyncSession) -> SystemState:
        settings = await SettingsRepository(session).get()
        orders = OrderRepository(session)
        if await orders.has_unknown():
            return await self._set_state(session, SystemState.RECOVERY, "unknown_orders_on_boot")
        if settings.estop:
            return await self._set_state(session, SystemState.STOPPED, "estop_latched")
        connected = await self._execution.health()
        if not connected:
            return await self._set_state(session, SystemState.CONNECTING, "worker_unreachable")
        if settings.trading_enabled:
            return await self._set_state(session, SystemState.RUNNING, "persisted_running")
        return await self._set_state(session, SystemState.STOPPED, "bootstrap")

    async def enter_recovery(self, session: AsyncSession, reason: str) -> SystemState:
        return await self._set_state(session, SystemState.RECOVERY, reason)

    async def set_state(self, session: AsyncSession, state: SystemState, reason: str) -> SystemState:
        return await self._set_state(session, state, reason)

    async def _set_state(self, session: AsyncSession, state: SystemState, reason: str) -> SystemState:
        settings = await SettingsRepository(session).get()
        previous = settings.system_state
        settings.system_state = state.value
        event = await EventRepository(session).add(
            "system_status",
            json.dumps({"from": previous, "to": state.value, "reason": reason}),
        )
        logger.info("system_state %s -> %s (%s)", previous, state.value, reason, extra=log_extra())
        await session.commit()
        await self._hub.publish("system_status", {"state": state.value, "reason": reason}, event.id)
        _ = PositionRepository  # imported to keep recovery module owning mirror updates later
        return state
