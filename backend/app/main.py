from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from secrets import compare_digest
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router as api_router
from app.api.ws import router as ws_router
from app.controllers.position_guard import PositionGuard
from app.controllers.trading_controller import TradingController
from app.core.config import Settings, get_settings
from app.db_backup import DatabaseBackupService
from app.core.logging import configure_logging
from app.db import configure_sqlite_pragma, create_all_for_tests, create_engine, create_session_factory
from app.deps import AppContainer
from app.events.hub import EventHub
from app.execution.client import HttpExecutionClient
from app.execution.protocol import ExecutionClient
from app.models import SettingsRow, StrategyParameter, StrategyVersion
from app.recovery.manager import RecoveryManager
from app.repositories import ReservationRepository, SettingsRepository, StrategyRepository
from app.strategy.service import StrategyService
from app.strategy.runtime import StrategyRuntime
from app.strategy.loop import StrategyLoop
from app.worker_heartbeat import WorkerHeartbeatService

_CONTAINER: AppContainer | None = None
logger = logging.getLogger(__name__)


def get_app_container() -> AppContainer:
    if _CONTAINER is None:
        raise RuntimeError("app container is not ready")
    return _CONTAINER


async def _add_example_hold(repo: StrategyRepository) -> None:
    hold = StrategyVersion(
        name="example_hold",
        version="1",
        file_hash="0" * 64,
        path="strategies/example_strategy/strategy.py",
        manifest_json='{"name":"example_hold"}',
    )
    await repo.add_version(hold)
    await repo.add_parameter(
        StrategyParameter(
            strategy_version_id=hold.id,
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


async def _add_ema5break(repo: StrategyRepository) -> None:
    ema = StrategyVersion(
        name="ema5break",
        version="1",
        file_hash="0" * 64,
        path="strategies/ema5break/strategy.py",
        manifest_json='{"name":"ema5break","interval":"5m","expected_leverage":3}',
    )
    await repo.add_version(ema)
    for name, typ, default, lo, hi, desc in (
        ("ema_period", "int", "5", "2", "50", "EMA length"),
        ("atr_period", "int", "14", "2", "50", "ATR lookback"),
        ("atr_stop_mult", "float", "2.0", "0.5", "10", "Stop in ATR multiples"),
        ("tp_rr", "float", "1.5", "0.5", "5", "Take-profit vs stop distance"),
    ):
        await repo.add_parameter(
            StrategyParameter(
                strategy_version_id=ema.id,
                name=name,
                type=typ,
                default_value=default,
                current_value=default,
                enabled=False,
                min_value=lo,
                max_value=hi,
                description=desc,
            )
        )


async def seed_defaults(container: AppContainer) -> None:
    resume_loop = False
    async with container.session_factory() as session:
        settings = await SettingsRepository(session).get()
        repo = StrategyRepository(session)
        versions = await repo.list_versions()
        names = {item.name for item in versions}
        added_ema = False
        if "example_hold" not in names:
            await _add_example_hold(repo)
        if "ema5break" not in names:
            await _add_ema5break(repo)
            added_ema = True
        if added_ema or settings.active_strategy in {"", "example_hold"}:
            settings.active_strategy = "ema5break"
            settings.active_strategy_version = "1"
            settings.trading_pair = "BTC-USD"
            settings.leverage = 3
        await ReservationRepository(session).ensure_slot()
        await session.commit()
        await container.controller.reconcile_after_restart(session)
        await container.recovery.bootstrap(session)
        settings = await SettingsRepository(session).get()
        if settings.trading_enabled and settings.system_state == "RUNNING":
            resumed = await container.controller.start(session)
            resume_loop = bool(resumed.get("ok"))
    if resume_loop:
        await container.strategy_loop.start()


def create_app(
    *,
    settings: Settings | None = None,
    execution: ExecutionClient | None = None,
    bootstrap_schema: bool = False,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    hub = EventHub()
    client = execution or HttpExecutionClient(
        settings.execution_worker_url,
        timeout=settings.execution_worker_write_timeout_seconds,
        read_timeout=settings.execution_worker_read_timeout_seconds,
    )
    recovery = RecoveryManager(client, hub)
    guard = PositionGuard()
    controller = TradingController(client, recovery, hub, guard)
    strategy_service = StrategyService(
        versions_root=Path(settings.strategies_dir),
        execution=client,
        hub=hub,
        recovery=recovery,
    )
    strategy_runtime = StrategyRuntime()
    strategy_loop = StrategyLoop(
        session_factory=session_factory, execution=client, runtime=strategy_runtime,
        controller=controller, hub=hub,
    )
    database_backup = DatabaseBackupService(
        settings.database_url,
        settings.database_backup_path,
        settings.database_backup_interval_seconds,
    )
    worker_heartbeat = WorkerHeartbeatService(client)
    container = AppContainer(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        execution=client,
        hub=hub,
        recovery=recovery,
        controller=controller,
        guard=guard,
        strategy_service=strategy_service,
        strategy_runtime=strategy_runtime,
        strategy_loop=strategy_loop,
        database_backup=database_backup,
        worker_heartbeat=worker_heartbeat,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        global _CONTAINER
        _CONTAINER = container
        await configure_sqlite_pragma(engine)
        # Production: Alembic upgrade head runs before uvicorn (Docker CMD).
        # Tests may pass bootstrap_schema=True to use create_all_for_tests.
        if bootstrap_schema:
            await create_all_for_tests(engine)
        await seed_defaults(container)
        try:
            await database_backup.backup_once()
        except Exception:
            logger.exception("initial SQLite backup failed")
        await database_backup.start()
        await worker_heartbeat.start()
        yield
        await worker_heartbeat.stop()
        await database_backup.stop()
        await strategy_loop.close()
        await engine.dispose()
        _CONTAINER = None

    app = FastAPI(title="newhbot", lifespan=lifespan)

    @app.middleware("http")
    async def control_plane_auth(request, call_next):
        if request.url.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if settings.execution_mode != "mock":
                token = settings.control_api_token
                supplied = request.headers.get("authorization", "")
                expected = f"Bearer {token}" if token else ""
                if not token or not compare_digest(supplied, expected):
                    return JSONResponse({"detail": "control API authentication required"}, status_code=401)
        return await call_next(request)
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
