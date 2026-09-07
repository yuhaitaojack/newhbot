from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import PositionSide, SignalType
from app.deps import AppContainer
from app.execution.protocol import BalanceView, PositionView
from app.models import StrategyParameter, StrategyVersion
from app.repositories import (
    AuditRepository,
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
    StrategyActivateIn,
    StrategyTickIn,
    StrategyOut,
    StrategyParameterOut,
    StrategyParameterUpdate,
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
    try:
        worker_ok = await container.execution.health()
    except Exception:
        return HealthOut(
            status="degraded",
            execution_mode=container.settings.execution_mode,
            worker_ok=False,
            worker_ready=False,
            worker_state="UNKNOWN",
            execution_enabled=False,
            sync_status="CONFLICT",
            hyperliquid_domain=None,
        )
    try:
        status = await container.execution.worker_status()
    except Exception:
        return HealthOut(
            status="degraded",
            execution_mode=container.settings.execution_mode,
            worker_ok=worker_ok,
            worker_ready=False,
            worker_state="UNKNOWN",
            execution_enabled=False,
            sync_status="CONFLICT",
            hyperliquid_domain=None,
        )
    worker_ready = bool(status.get("ready"))
    return HealthOut(
        status="ok" if worker_ok and worker_ready else "degraded",
        execution_mode=container.settings.execution_mode,
        worker_ok=worker_ok,
        worker_ready=worker_ready,
        worker_state=status.get("worker_state"),
        execution_enabled=bool(status.get("execution_enabled", False)),
        sync_status=status.get("sync_status"),
        hyperliquid_domain=status.get("hyperliquid_domain"),
    )


@router.get("/status", response_model=StatusOut)
async def status(session: AsyncSession = Depends(get_session)) -> StatusOut:
    container = _container()
    settings_row = await SettingsRepository(session).get()
    position_row = await PositionRepository(session).get_or_none(settings_row.trading_pair)
    orders = await OrderRepository(session).list_recent(1)
    fills = await FillRepository(session).list_recent(1)
    signal = await SignalRepository(session).latest()
    snapshot = await SnapshotRepository(session).latest()
    try:
        live = await container.execution.get_position(settings_row.trading_pair)
        balance = await container.execution.get_balance()
        position_row = await PositionRepository(session).upsert_mirror(
            settings_row.trading_pair, live.side, live.size, live.entry_price, live.unrealized_pnl
        )
        await session.commit()
        if live.side == PositionSide.UNKNOWN:
            await container.controller.enter_recovery(session, "status_position_unknown")
            await container.strategy_loop.stop()
    except Exception as exc:
        await container.controller.enter_recovery(session, f"status_exchange_query_failed:{type(exc).__name__}")
        await container.strategy_loop.stop()
        if position_row is None:
            live = PositionView(
                symbol=settings_row.trading_pair,
                side=PositionSide.UNKNOWN,
                size=Decimal("0"),
                entry_price=None,
                unrealized_pnl=Decimal("0"),
            )
        else:
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
    try:
        worker = await container.execution.worker_status()
    except Exception as exc:
        await container.controller.enter_recovery(session, f"status_worker_query_failed:{type(exc).__name__}")
        await container.strategy_loop.stop()
        worker = {
            "ready": False,
            "worker_state": "UNKNOWN",
            "sync_status": "CONFLICT",
        }
    return StatusOut(
        system_state=settings_row.system_state,  # type: ignore[arg-type]
        trading_enabled=settings_row.trading_enabled,
        estop=settings_row.estop,
        last_signal=signal.signal if signal else None,  # type: ignore[arg-type]
        last_signal_reason=signal.reason if signal else None,
        settings=_settings_out(settings_row),
        position=_position_out(position_row, settings_row.trading_pair, live),
        last_order=_order_out(last_order) if last_order else None,
        last_fill=_fill_out(last_fill) if last_fill else None,
        balance={"equity": balance.equity, "available": balance.available, "margin_used": balance.margin_used},
        snapshot_event_id=last_event,
        worker_ready=bool(worker.get("ready")),
        worker_state=worker.get("worker_state"),
        sync_status=worker.get("sync_status"),
        hyperliquid_domain=worker.get("hyperliquid_domain"),
        strategy_loop_running=container.strategy_loop.running,
        strategy_loop_last_error=container.strategy_loop.last_error,
        strategy_loop_last_candle_timestamp=container.strategy_loop.last_candle_timestamp,
    )


@router.get("/settings", response_model=SettingsOut)
async def get_settings(session: AsyncSession = Depends(get_session)) -> SettingsOut:
    row = await SettingsRepository(session).get()
    return _settings_out(row)


@router.put("/settings", response_model=SettingsOut)
async def put_settings(body: SettingsUpdate, session: AsyncSession = Depends(get_session)) -> SettingsOut:
    from app.repositories import AuditRepository

    row = await SettingsRepository(session).get()
    if row.system_state != "STOPPED" or row.trading_enabled:
        raise HTTPException(
            status_code=409,
            detail="settings can only be changed while trading is STOPPED",
        )
    data = body.model_dump(exclude_unset=True)
    data.pop("estop", None)
    data.pop("active_strategy", None)
    data.pop("active_strategy_version", None)
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
    active = next(
        (
            item
            for item in versions
            if item.name == settings.active_strategy
            and item.version == settings.active_strategy_version
        ),
        None,
    )
    chosen = active or (versions[0] if versions else None)
    if chosen is not None:
        raw_params = await repo.parameters_for(chosen.id)
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


def _validate_strategy_parameter_value(param: StrategyParameter, value: str) -> str:
    kind = param.type.strip().lower()
    try:
        if kind in {"int", "integer"}:
            if not re.fullmatch(r"[+-]?\d+", value.strip()):
                raise ValueError
            parsed: int | Decimal = int(value.strip())
        elif kind in {"float", "number", "decimal"}:
            parsed = Decimal(value.strip())
            if not parsed.is_finite():
                raise ValueError
        elif kind in {"bool", "boolean"}:
            if value.strip().lower() not in {"true", "false"}:
                raise ValueError
            parsed = value.strip().lower() == "true"
        elif kind in {"string", "str"}:
            parsed = value
        else:
            raise HTTPException(status_code=422, detail=f"unsupported strategy parameter type: {param.type}")
    except (ValueError, ArithmeticError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid value for parameter {param.name}") from exc

    if kind not in {"string", "str", "bool", "boolean"}:
        try:
            if param.min_value is not None and parsed < Decimal(param.min_value):
                raise HTTPException(status_code=422, detail=f"parameter {param.name} is below minimum")
            if param.max_value is not None and parsed > Decimal(param.max_value):
                raise HTTPException(status_code=422, detail=f"parameter {param.name} is above maximum")
        except (ValueError, ArithmeticError) as exc:
            raise HTTPException(status_code=422, detail=f"invalid bounds for parameter {param.name}") from exc
    return value


@router.put("/strategy/parameters/{parameter_id}", response_model=StrategyParameterOut)
async def put_strategy_parameter(
    parameter_id: int,
    body: StrategyParameterUpdate,
    session: AsyncSession = Depends(get_session),
) -> StrategyParameterOut:
    settings = await SettingsRepository(session).get()
    if settings.system_state != "STOPPED" or settings.trading_enabled:
        raise HTTPException(status_code=409, detail="strategy parameters can only be changed while trading is STOPPED")
    versions = await StrategyRepository(session).list_versions()
    active = next(
        (item for item in versions if item.name == settings.active_strategy and item.version == settings.active_strategy_version),
        None,
    )
    if active is None:
        raise HTTPException(status_code=409, detail="active strategy version is unavailable")
    param = await StrategyRepository(session).get_parameter(parameter_id)
    if param is None or param.strategy_version_id != active.id:
        raise HTTPException(status_code=404, detail="strategy parameter not found")
    if body.current_value is not None:
        param.current_value = _validate_strategy_parameter_value(param, body.current_value)
    if body.enabled is not None:
        param.enabled = body.enabled
    await AuditRepository(session).add(
        "update_strategy_parameter",
        json.dumps({"id": param.id, "name": param.name, "enabled": param.enabled, "current_value": param.current_value}),
        actor="user",
    )
    await session.commit()
    return StrategyParameterOut(
        id=param.id,
        name=param.name,
        type=param.type,
        default_value=param.default_value,
        current_value=param.current_value,
        enabled=param.enabled,
        min_value=param.min_value,
        max_value=param.max_value,
        description=param.description,
        effective_value=effective_parameter_value(param),
    )


async def _read_form_bytes(item) -> tuple[str | None, bytes]:
    if item is None:
        return None, b""
    filename = getattr(item, "filename", None)
    if hasattr(item, "read"):
        data = await item.read()
        if isinstance(data, str):
            data = data.encode("utf-8")
        return filename, data
    if isinstance(item, (bytes, bytearray)):
        return filename, bytes(item)
    return filename, str(item).encode("utf-8")


@router.post("/strategy/upload")
async def strategy_upload(request: Request, session: AsyncSession = Depends(get_session)) -> dict:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type.lower():
        return JSONResponse(
            {"ok": False, "reason": "multipart form with strategy.py and manifest.yaml is required"},
            status_code=400,
        )
    form = await request.form()
    try:
        field_names = set(form.keys())
        strategy_name, strategy_py = await _read_form_bytes(form.get("strategy.py"))
        manifest_name, manifest_yaml = await _read_form_bytes(form.get("manifest.yaml"))
        result = await _container().strategy_service.upload(
            session,
            field_names=field_names,
            strategy_name=strategy_name,
            manifest_name=manifest_name,
            strategy_py=strategy_py,
            manifest_yaml=manifest_yaml,
        )
    finally:
        for value in form.values():
            close = getattr(value, "close", None)
            if close is not None:
                await close()
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    return result


@router.post("/strategy/activate")
async def strategy_activate(body: StrategyActivateIn, session: AsyncSession = Depends(get_session)) -> dict:
    return await _container().strategy_service.activate(session, body.file_hash)


@router.get("/preflight")
async def preflight(session: AsyncSession = Depends(get_session)) -> dict:
    """Read-only live-trading readiness report. Never arms or submits anything."""
    container = _container()
    settings = await SettingsRepository(session).get()
    reasons: list[str] = []
    checks: dict[str, object] = {
        "execution_mode": container.settings.execution_mode,
        "execution_enabled": False,
        "worker_ready": False,
        "control_api_token_configured": bool(container.settings.control_api_token),
        "system_state": settings.system_state,
        "estop": settings.estop,
    }
    if container.settings.execution_mode != "hyperliquid":
        reasons.append("execution mode is not hyperliquid")
    if not container.settings.control_api_token:
        reasons.append("CONTROL_API_TOKEN is not configured")
    if settings.system_state != "STOPPED":
        reasons.append(f"system state is {settings.system_state}, expected STOPPED")
    if settings.estop:
        reasons.append("emergency stop is latched")
    try:
        worker = await container.execution.worker_status()
        checks["execution_enabled"] = bool(worker.get("execution_enabled", False))
        checks["worker_ready"] = bool(worker.get("ready", False))
        checks["worker_state"] = worker.get("worker_state")
        checks["sync_status"] = worker.get("sync_status")
        if not checks["execution_enabled"]:
            reasons.append("worker execution is disabled")
        if not checks["worker_ready"]:
            reasons.append("worker is not ready")
    except Exception as exc:
        reasons.append(f"worker status failed: {type(exc).__name__}")
    try:
        position = await container.execution.get_position(settings.trading_pair)
        checks["position"] = {"side": position.side.value, "size": str(position.size)}
        if position.side != PositionSide.FLAT:
            reasons.append("configured trading pair is not FLAT")
    except Exception as exc:
        reasons.append(f"position query failed: {type(exc).__name__}")
    try:
        positions = await container.execution.get_positions()
        checks["position_count"] = len(positions)
        if len(positions) > 1:
            reasons.append("more than one exchange position exists")
        if any(item.symbol != settings.trading_pair for item in positions):
            reasons.append("foreign exchange position exists")
    except Exception as exc:
        reasons.append(f"positions query failed: {type(exc).__name__}")
    try:
        open_orders = await container.execution.get_open_orders()
        checks["open_order_count"] = len(open_orders)
        if open_orders:
            reasons.append("exchange has open orders")
    except Exception as exc:
        reasons.append(f"open orders query failed: {type(exc).__name__}")
    if await OrderRepository(session).has_unresolved():
        reasons.append("local unresolved or UNKNOWN orders exist")
    try:
        balance = await container.execution.get_balance()
        checks["equity"] = str(balance.equity)
        checks["available"] = str(balance.available)
        if balance.equity <= 0:
            reasons.append("exchange equity is not positive")
        if balance.available <= 0:
            reasons.append("exchange available balance is not positive")
    except Exception as exc:
        reasons.append(f"balance query failed: {type(exc).__name__}")
    versions = await StrategyRepository(session).list_versions()
    active = next((item for item in versions if item.name == settings.active_strategy and item.version == settings.active_strategy_version), None)
    checks["active_strategy"] = settings.active_strategy
    checks["active_strategy_version"] = settings.active_strategy_version
    if active is None:
        reasons.append("active strategy version is unavailable")
    elif not (Path(active.path) / "strategy.py").is_file() and not Path(active.path).is_file():
        reasons.append("active strategy.py is unavailable")
    checks["ready_for_live"] = not reasons
    checks["reasons"] = reasons
    return checks


@router.get("/market/candles")
async def market_candles(
    symbol: str,
    interval: str = Query(default="5m", pattern=r"^[0-9]+[smhdM]$"),
    limit: int = Query(default=200, ge=2, le=5000),
) -> list[dict]:
    """Read-only candles; disabled in mock to avoid accidental public calls."""
    container = _container()
    if container.settings.execution_mode != "hyperliquid":
        raise HTTPException(status_code=403, detail="live candle source is disabled in mock mode")
    try:
        return await container.execution.get_candles(symbol, interval, limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"candle source unavailable: {type(exc).__name__}") from exc

@router.post("/strategy/tick")
async def strategy_tick(body: StrategyTickIn, session: AsyncSession = Depends(get_session)) -> dict:
    """Evaluate one mock snapshot and route the result through Trading Controller."""
    container = _container()
    if container.settings.execution_mode != "mock":
        raise HTTPException(status_code=403, detail="strategy tick is available only in mock mode")
    settings = await SettingsRepository(session).get()
    versions = await StrategyRepository(session).list_versions()
    version = next(
        (item for item in versions
         if item.name == settings.active_strategy and item.version == settings.active_strategy_version),
        None,
    )


    if version is None:
        raise HTTPException(status_code=409, detail="active strategy version is unavailable")
    snapshot = dict(body.snapshot)
    try:
        live = await container.execution.get_position(settings.trading_pair)
    except Exception as exc:
        reason = f"strategy_tick_position_query_failed:{type(exc).__name__}"
        await container.controller.enter_recovery(session, reason)
        return {
            "ok": False,
            "signal": SignalType.HOLD.value,
            "reason": reason,
            "controller": {"accepted": False, "reason": "recovery required"},
        }
    if live.side == PositionSide.UNKNOWN:
        reason = "strategy_tick_position_unknown"
        await container.controller.enter_recovery(session, reason)
        return {
            "ok": False,
            "signal": SignalType.HOLD.value,
            "reason": reason,
            "controller": {"accepted": False, "reason": "recovery required"},
        }
    snapshot.update({
        "symbol": settings.trading_pair,
        "position_side": live.side.value,
        "entry_price": str(live.entry_price) if live.entry_price is not None else None,
    })
    parameters = await StrategyRepository(session).parameters_for(version.id)
    snapshot["parameters"] = {item.name: effective_parameter_value(item) for item in parameters}
    try:
        evaluated = await container.strategy_runtime.evaluate(version.path, snapshot)
        signal = SignalType(evaluated["signal"])
    except Exception as exc:
        await AuditRepository(session).add(
            "strategy_tick_rejected",
            json.dumps({"strategy": version.name, "version": version.version, "reason": str(exc)}),
            actor="strategy_runtime",
        )
        await session.commit()
        return {"ok": False, "signal": SignalType.HOLD.value, "reason": str(exc)}
    result = await container.controller.handle_signal(session, signal, actor="strategy_runtime")
    await AuditRepository(session).add(
        "strategy_tick",
        json.dumps({"strategy": version.name, "version": version.version, "signal": signal.value}),
        actor="strategy_runtime",
    )
    await session.commit()
    return {"ok": True, "signal": signal.value, "reason": evaluated.get("reason"), "controller": result}


@router.get("/strategy/loop")
async def strategy_loop_status() -> dict:
    loop = _container().strategy_loop
    return {"running": loop.running, "last_error": loop.last_error, "last_candle_timestamp": loop.last_candle_timestamp}


@router.post("/strategy/loop/start")
async def strategy_loop_start(session: AsyncSession = Depends(get_session)) -> dict:
    container = _container()
    if container.settings.execution_mode not in {"mock", "hyperliquid"}:
        raise HTTPException(status_code=403, detail="unsupported execution mode")
    settings = await SettingsRepository(session).get()
    if not settings.trading_enabled or settings.system_state != "RUNNING":
        raise HTTPException(status_code=409, detail="strategy loop requires trading state RUNNING")
    return await container.strategy_loop.start()


@router.post("/strategy/loop/stop")
async def strategy_loop_stop() -> dict:
    return await _container().strategy_loop.stop()


@router.get("/positions", response_model=list[PositionOut])
async def get_positions(session: AsyncSession = Depends(get_session)) -> list[PositionOut]:
    settings = await SettingsRepository(session).get()
    row = await PositionRepository(session).get_or_none(settings.trading_pair)
    if row is None:
        return []
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
    container = _container()
    result = await container.controller.start(session)
    if result.get("ok"):
        await container.strategy_loop.start()
    return result


@router.post("/trading/stop")
async def trading_stop(session: AsyncSession = Depends(get_session)) -> dict:
    container = _container()
    await container.strategy_loop.stop()
    return await container.controller.stop(session)


@router.post("/trading/close-and-stop")
async def trading_close_and_stop(session: AsyncSession = Depends(get_session)) -> dict:
    container = _container()
    await container.strategy_loop.stop()
    return await container.controller.close_and_stop(session)


@router.post("/trading/close-and-continue")
async def trading_close_and_continue(session: AsyncSession = Depends(get_session)) -> dict:
    container = _container()
    result = await container.controller.close_and_continue(session)
    if not result.get("ok"):
        settings = await SettingsRepository(session).get()
        if settings.system_state == "RECOVERY":
            await container.strategy_loop.stop()
        return result
    # "继续运行" includes the supervised strategy loop. Only restart it after
    # a confirmed close result and while the controller left the system RUNNING;
    # never restart a loop from Recovery or another unsafe state.
    settings = await SettingsRepository(session).get()
    if settings.trading_enabled and settings.system_state == "RUNNING":
        await container.strategy_loop.start()
    return result


@router.post("/trading/emergency-stop")
async def trading_emergency_stop(session: AsyncSession = Depends(get_session)) -> dict:
    container = _container()
    await container.strategy_loop.stop()
    return await container.controller.emergency_stop(session)


@router.post("/trading/clear-estop")
async def trading_clear_estop(session: AsyncSession = Depends(get_session)) -> dict:
    return await _container().controller.clear_estop(session)


@router.post("/trading/signal")
async def trading_signal(body: dict, session: AsyncSession = Depends(get_session)) -> dict:
    """Test/dev helper. Production strategy runtime will call the controller internally."""
    if _container().settings.execution_mode != "mock":
        raise HTTPException(status_code=403, detail="direct signal injection is available only in mock mode")

    signal_raw = body.get("signal")
    try:
        signal = SignalType(signal_raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="signal must be LONG/SHORT/CLOSE/HOLD") from exc
    return await _container().controller.handle_signal(session, signal, actor="api")


def _position_out(row, symbol: str, fallback: PositionView | None = None) -> PositionOut:
    if row is not None:
        return PositionOut(
            symbol=row.symbol,
            side=PositionSide(row.side),
            size=row.size,
            entry_price=row.entry_price,
            unrealized_pnl=row.unrealized_pnl,
            source=row.source,
        )
    return PositionOut(
        symbol=symbol,
        side=fallback.side if fallback is not None else PositionSide.UNKNOWN,
        size=fallback.size if fallback is not None else Decimal("0"),
        entry_price=fallback.entry_price if fallback is not None else None,
        unrealized_pnl=fallback.unrealized_pnl if fallback is not None else Decimal("0"),
        source="unsynced",
    )


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
        exchange_fill_id=row.exchange_fill_id,
    )


# Imported by seed helper
StrategyParameter
StrategyVersion
