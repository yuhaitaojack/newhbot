from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.controllers.position_guard import PositionGuard
from app.controllers.trading_controller import TradingController
from app.core.config import Settings
from app.db_backup import DatabaseBackupService
from app.events.hub import EventHub
from app.execution.protocol import ExecutionClient
from app.recovery.manager import RecoveryManager
from app.strategy.service import StrategyService
from app.strategy.runtime import StrategyRuntime
from app.strategy.loop import StrategyLoop
from app.worker_heartbeat import WorkerHeartbeatService


@dataclass
class AppContainer:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    execution: ExecutionClient
    hub: EventHub
    recovery: RecoveryManager
    controller: TradingController
    guard: PositionGuard
    strategy_service: StrategyService
    strategy_runtime: StrategyRuntime
    strategy_loop: StrategyLoop
    database_backup: DatabaseBackupService
    worker_heartbeat: WorkerHeartbeatService


def get_container(request_container: AppContainer | None = None) -> AppContainer:
    if request_container is None:
        raise RuntimeError("container is not initialized")
    return request_container


async def db_session(container: AppContainer) -> AsyncIterator[AsyncSession]:
    async with container.session_factory() as session:
        yield session
