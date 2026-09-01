from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.api.ws import router as ws_router
from app.controllers.position_guard import PositionGuard
from app.controllers.trading_controller import TradingController
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db import Base, configure_sqlite_pragma, create_engine, create_session_factory
from app.deps import AppContainer
from app.events.hub import EventHub
from app.execution.client import HttpExecutionClient
from app.execution.protocol import ExecutionClient
from app.models import SettingsRow  # noqa: F401
from app.recovery.manager import RecoveryManager
from app.repositories import SettingsRepository, StrategyRepository
from app.models import StrategyParameter, StrategyVersion

_CONTAINER: AppContainer | None = None


def get_app_container() -> AppContainer:
    if _CONTAINER is None:
        raise RuntimeError("app container is not ready")
    return _CONTAINER


async def seed_defaults(container: AppContainer) -> None:
    async with container.session_factory() as session:
        settings = await SettingsRepository(session).get()
        repo = StrategyRepository(session)
        versions = await repo.list_versions()
        if not versions:
            version = StrategyVersion(
                name="example_hold",
                version="1",
                file_hash="0" * 64,
                path="strategies/example_strategy/strategy.py",
                manifest_json='{"name":"example_hold"}',
            )
            await repo.add_version(version)
            await repo.add_parameter(
                StrategyParameter(
                    strategy_version_id=version.id,
                    name="lookback",
                    type="int",
                    default_value="20",
                    current_value="20",
                    enabled=False,
                    min_value="1",
                    max_value="200",
                    description="Unused example lookback",
                )
            )
            settings.active_strategy = "example_hold"
            settings.active_strategy_version = "1"
        await session.commit()
        await container.recovery.bootstrap(session)


def create_app(
    *,
    settings: Settings | None = None,
    execution: ExecutionClient | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    hub = EventHub()
    client = execution or HttpExecutionClient(settings.execution_worker_url)
    recovery = RecoveryManager(client, hub)
    guard = PositionGuard()
    controller = TradingController(client, recovery, hub, guard)
    container = AppContainer(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        execution=client,
        hub=hub,
        recovery=recovery,
        controller=controller,
        guard=guard,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        global _CONTAINER
        _CONTAINER = container
        await configure_sqlite_pragma(engine)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await seed_defaults(container)
        yield
        await engine.dispose()
        _CONTAINER = None

    app = FastAPI(title="newhbot", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix="/api")
    app.include_router(ws_router)
    app.state.container = container
    return app


app = create_app()
