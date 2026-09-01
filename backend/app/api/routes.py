from __future__ import annotations

import json
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import PositionSide
from app.deps import AppContainer
from app.execution.protocol import BalanceView, PositionView
from app.models import StrategyParameter, StrategyVersion
from app.repositories import (
    EventRepository,
    FillRepository,
    OrderRepository,
    PositionRepository,
    SettingsRepository,
    SignalRepository,
    SnapshotRepository,
    StrategyRepository,
    TradeRepository,
    effective_parameter_value,
)
from app.schemas import (
    EventOut,
    FillOut,
    HealthOut,
    OrderOut,
    PositionOut,
    SettingsOut,
    SettingsUpdate,
    StatusOut,
    StrategyOut,
    StrategyParameterOut,
    StrategyVersionOut,
    TradeOut,
)

router = APIRouter()


def _container() -> AppContainer:
    from app.main import get_app_container

    return get_app_container()


async def get_session() -> AsyncSession:
    container = _container()
    async with container.session_factory() as session:
        yield session


def _settings_out(row) -> SettingsOut:
    return SettingsOut(
        trading_pair=row.trading_pair,
        leverage=row.leverage,
        position_percentage=row.position_percentage,
        order_type=row.order_type,
        limit_timeout=row.limit_timeout,
        slippage=row.slippage,
        active_strategy=row.active_strategy,
        active_strategy_version=row.active_strategy_version,
        trading_enabled=row.trading_enabled,
        estop=row.estop,
        close_intent=row.close_intent,
        system_state=row.system_state,
    )


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    container = _container()
    worker_ok = await container.execution.health()
    status = await container.execution.worker_status()
    return HealthOut(
        status="ok",
        execution_mode=container.settings.execution_mode,
        worker_ok=worker_ok,
        worker_ready=bool(status.get("ready")),
        worker_state=status.get("worker_state"),
        execution_enabled=bool(status.get("execution_enabled", False)),
        sync_status=status.get("sync_status"),
    )


@router.get("/status", response_model=StatusOut)
async def status(session: AsyncSession = Depends(get_session)) -> StatusOut:
    container = _container()
    settings_row = await SettingsRepository(session).get()
    position_row = await PositionRepository(session).get(settings_row.trading_pair)
    orders = await OrderRepository(session).list_recent(1)
    fills = await FillRepository(session).list_recent(1)
    signal = await SignalRepository(session).latest()
    snapshot = await SnapshotRepository(session).latest()
    try:
        live = await container.execution.get_position(settings_row.trading_pair)
        balance = await container.execution.get_balance()
        await PositionRepository(session).upsert_mirror(
            settings_row.trading_pair, live.side, live.size, live.entry_price, live.unrealized_pnl
        )
        await session.commit()
        position_row = await PositionRepository(session).get(settings_row.trading_pair)
    except Exception:
        live = PositionView(
            symbol=settings_row.trading_pair,
            side=PositionSide(position_row.side),
            size=position_row.size,
            entry_price=position_row.entry_price,
            unrealized_pnl=position_row.unrealized_pnl,
        )
        balance = BalanceView(
            equity=snapshot.equity if snapshot else Decimal("0"),
            available=snapshot.available if snapshot else Decimal("0"),
            margin_used=snapshot.margin_used if snapshot else Decimal("0"),
        )
    last_event = await EventRepository(session).max_id()
    last_order = orders[0] if orders else None
    last_fill = fills[0] if fills else None
    worker = await container.execution.worker_status()
    return StatusOut(
        system_state=settings_row.system_state,  # type: ignore[arg-type]
        trading_enabled=settings_row.trading_enabled,
        estop=settings_row.estop,
        last_signal=signal.signal if signal else None,  # type: ignore[arg-type]
        last_signal_reason=signal.reason if signal else None,
        settings=_settings_out(settings_row),
        position=PositionOut(
            symbol=position_row.symbol,
            side=PositionSide(position_row.side),
            size=position_row.size,
            entry_price=position_row.entry_price,
            unrealized_pnl=position_row.unrealized_pnl,
            source=position_row.source,
        ),
        last_order=_order_out(last_order) if last_order else None,
        last_fill=_fill_out(last_fill) if last_fill else None,
        balance={"equity": balance.equity, "available": balance.available, "margin_used": balance.margin_used},
        snapshot_event_id=last_event,
        worker_ready=bool(worker.get("ready")),
        worker_state=worker.get("worker_state"),
        sync_status=worker.get("sync_status"),
    )


@router.get("/settings", response_model=SettingsOut)
async def get_settings(session: AsyncSession = Depends(get_session)) -> SettingsOut:
    row = await SettingsRepository(session).get()
    return _settings_out(row)


@router.put("/settings", response_model=SettingsOut)
async def put_settings(body: SettingsUpdate, session: AsyncSession = Depends(get_session)) -> SettingsOut:
    from app.repositories import AuditRepository

    row = await SettingsRepository(session).get()
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(row, key, value)
    await AuditRepository(session).add("update_settings", json.dumps(data, default=str))
    await session.commit()
    await session.refresh(row)
    return _settings_out(row)


@router.get("/strategy", response_model=StrategyOut)
async def get_strategy(session: AsyncSession = Depends(get_session)) -> StrategyOut:
    settings = await SettingsRepository(session).get()
    repo = StrategyRepository(session)
    versions = await repo.list_versions()
    params: list[StrategyParameterOut] = []
    if versions:
        raw_params = await repo.parameters_for(versions[0].id)
        params = [
            StrategyParameterOut(
                id=item.id,
                name=item.name,
                type=item.type,
                default_value=item.default_value,
                current_value=item.current_value,
                enabled=item.enabled,
                min_value=item.min_value,
                max_value=item.max_value,
                description=item.description,
                effective_value=effective_parameter_value(item),
            )
            for item in raw_params
        ]
    return StrategyOut(
        active_strategy=settings.active_strategy,
        active_strategy_version=settings.active_strategy_version,
        versions=[
            StrategyVersionOut(
                id=item.id,
                name=item.name,
                version=item.version,
                file_hash=item.file_hash,
                path=item.path,
                created_at=item.created_at,
            )
            for item in versions
        ],
        parameters=params,
    )


@router.get("/strategy/versions", response_model=list[StrategyVersionOut])
async def get_strategy_versions(session: AsyncSession = Depends(get_session)) -> list[StrategyVersionOut]:
    versions = await StrategyRepository(session).list_versions()
    return [
        StrategyVersionOut(
            id=item.id,
            name=item.name,
            version=item.version,
            file_hash=item.file_hash,
            path=item.path,
            created_at=item.created_at,
        )
        for item in versions
    ]


@router.get("/positions", response_model=list[PositionOut])
async def get_positions(session: AsyncSession = Depends(get_session)) -> list[PositionOut]:
    settings = await SettingsRepository(session).get()
    row = await PositionRepository(session).get(settings.trading_pair)
    return [
        PositionOut(
            symbol=row.symbol,
            side=PositionSide(row.side),
            size=row.size,
            entry_price=row.entry_price,
            unrealized_pnl=row.unrealized_pnl,
            source=row.source,
        )
    ]


@router.get("/orders", response_model=list[OrderOut])
async def get_orders(session: AsyncSession = Depends(get_session)) -> list[OrderOut]:
    rows = await OrderRepository(session).list_recent()
    return [_order_out(row) for row in rows]


@router.get("/fills", response_model=list[FillOut])
async def get_fills(session: AsyncSession = Depends(get_session)) -> list[FillOut]:
    rows = await FillRepository(session).list_recent()
    return [_fill_out(row) for row in rows]


@router.get("/trades", response_model=list[TradeOut])
async def get_trades(session: AsyncSession = Depends(get_session)) -> list[TradeOut]:
    rows = await TradeRepository(session).list_recent()
    return [
        TradeOut(
            id=row.id,
            symbol=row.symbol,
            side=row.side,
            entry_price=row.entry_price,
            exit_price=row.exit_price,
            quantity=row.quantity,
            pnl=row.pnl,
            opened_at=row.opened_at,
            closed_at=row.closed_at,
        )
        for row in rows
    ]


@router.get("/events", response_model=list[EventOut])
async def get_events(session: AsyncSession = Depends(get_session)) -> list[EventOut]:
    rows = await EventRepository(session).list_recent()
    return [
        EventOut(id=row.id, event_type=row.event_type, payload_json=row.payload_json, created_at=row.created_at)
        for row in rows
    ]


@router.post("/trading/start")
async def trading_start(session: AsyncSession = Depends(get_session)) -> dict:
    return await _container().controller.start(session)


@router.post("/trading/stop")
async def trading_stop(session: AsyncSession = Depends(get_session)) -> dict:
    return await _container().controller.stop(session)


@router.post("/trading/close-and-stop")
async def trading_close_and_stop(session: AsyncSession = Depends(get_session)) -> dict:
    return await _container().controller.close_and_stop(session)


@router.post("/trading/close-and-continue")
async def trading_close_and_continue(session: AsyncSession = Depends(get_session)) -> dict:
    return await _container().controller.close_and_continue(session)


@router.post("/trading/emergency-stop")
async def trading_emergency_stop(session: AsyncSession = Depends(get_session)) -> dict:
    return await _container().controller.emergency_stop(session)


@router.post("/trading/signal")
async def trading_signal(body: dict, session: AsyncSession = Depends(get_session)) -> dict:
    """Test/dev helper. Production strategy runtime will call the controller internally."""
    from app.core.enums import SignalType

    signal_raw = body.get("signal")
    try:
        signal = SignalType(signal_raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="signal must be LONG/SHORT/CLOSE/HOLD") from exc
    return await _container().controller.handle_signal(session, signal, actor="api")


def _order_out(row) -> OrderOut:
    return OrderOut(
        id=row.id,
        intent_id=row.intent_id,
        request_id=row.request_id,
        cloid=row.cloid,
        exchange_oid=row.exchange_oid,
        symbol=row.symbol,
        side=row.side,
        order_type=row.order_type,
        quantity=row.quantity,
        reduce_only=row.reduce_only,
        status=row.status,
        signal_id=row.signal_id,
        error_message=row.error_message,
        created_at=row.created_at,
    )


def _fill_out(row) -> FillOut:
    return FillOut(
        id=row.id,
        order_id=row.order_id,
        cloid=row.cloid,
        symbol=row.symbol,
        side=row.side,
        price=row.price,
        quantity=row.quantity,
        fee=row.fee,
        created_at=row.created_at,
    )


# Imported by seed helper
StrategyParameter
StrategyVersion
