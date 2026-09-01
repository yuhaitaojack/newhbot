from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import UNRESOLVED_ORDER_STATUSES, OrderStatus, PositionSide
from app.models import (
    AccountSnapshot,
    AuditLog,
    Fill,
    OpenReservation,
    Order,
    Position,
    SettingsRow,
    Signal,
    StrategyParameter,
    StrategyVersion,
    SystemEvent,
    Trade,
)


class SettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self) -> SettingsRow:
        row = await self._session.get(SettingsRow, 1)
        if row is None:
            row = SettingsRow(id=1)
            self._session.add(row)
            await self._session.flush()
        return row

    async def save(self, row: SettingsRow) -> SettingsRow:
        await self._session.flush()
        return row


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, order: Order) -> Order:
        self._session.add(order)
        await self._session.flush()
        return order

    async def get_by_cloid(self, cloid: str) -> Order | None:
        result = await self._session.execute(select(Order).where(Order.cloid == cloid))
        return result.scalar_one_or_none()

    async def list_recent(self, limit: int = 100) -> Sequence[Order]:
        result = await self._session.execute(select(Order).order_by(Order.created_at.desc()).limit(limit))
        return result.scalars().all()

    async def has_unknown(self) -> bool:
        return await self.has_unresolved()

    async def has_unresolved(self) -> bool:
        result = await self._session.execute(
            select(Order.id)
            .where(Order.status.in_([item.value for item in UNRESOLVED_ORDER_STATUSES]))
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def list_unresolved(self) -> Sequence[Order]:
        result = await self._session.execute(
            select(Order)
            .where(Order.status.in_([item.value for item in UNRESOLVED_ORDER_STATUSES]))
            .order_by(Order.created_at.asc())
        )
        return result.scalars().all()

    async def list_open(self) -> Sequence[Order]:
        result = await self._session.execute(
            select(Order).where(Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIAL]))
        )
        return result.scalars().all()


class PositionRepository:
    """Writes local MIRROR rows. Exchange State > Local DB."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, symbol: str) -> Position:
        result = await self._session.execute(select(Position).where(Position.symbol == symbol))
        row = result.scalar_one_or_none()
        if row is None:
            row = Position(symbol=symbol, side=PositionSide.FLAT.value, size=Decimal("0"))
            self._session.add(row)
            await self._session.flush()
        return row

    async def upsert_mirror(
        self,
        symbol: str,
        side: PositionSide,
        size: Decimal,
        entry_price: Decimal | None,
        unrealized_pnl: Decimal,
    ) -> Position:
        row = await self.get(symbol)
        row.side = side.value
        row.size = size
        row.entry_price = entry_price
        row.unrealized_pnl = unrealized_pnl
        row.source = "exchange_mirror"
        await self._session.flush()
        return row


class SignalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, signal: Signal) -> Signal:
        self._session.add(signal)
        await self._session.flush()
        return signal

    async def latest(self) -> Signal | None:
        result = await self._session.execute(select(Signal).order_by(Signal.created_at.desc()).limit(1))
        return result.scalar_one_or_none()


class FillRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_exchange_fill_id(self, exchange_fill_id: str) -> Fill | None:
        result = await self._session.execute(select(Fill).where(Fill.exchange_fill_id == exchange_fill_id))
        return result.scalar_one_or_none()

    async def add(self, fill: Fill) -> tuple[Fill, bool]:
        if fill.exchange_fill_id:
            existing = await self.get_by_exchange_fill_id(fill.exchange_fill_id)
            if existing is not None:
                return existing, False
        self._session.add(fill)
        await self._session.flush()
        return fill, True

    async def list_recent(self, limit: int = 100) -> Sequence[Fill]:
        result = await self._session.execute(select(Fill).order_by(Fill.created_at.desc()).limit(limit))
        return result.scalars().all()

    async def latest(self) -> Fill | None:
        result = await self._session.execute(select(Fill).order_by(Fill.created_at.desc()).limit(1))
        return result.scalar_one_or_none()


class TradeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, trade: Trade) -> Trade:
        self._session.add(trade)
        await self._session.flush()
        return trade

    async def list_recent(self, limit: int = 100) -> Sequence[Trade]:
        result = await self._session.execute(select(Trade).order_by(Trade.opened_at.desc()).limit(limit))
        return result.scalars().all()

    async def open_trade(self, symbol: str) -> Trade | None:
        result = await self._session.execute(
            select(Trade).where(Trade.symbol == symbol, Trade.closed_at.is_(None)).order_by(Trade.opened_at.desc())
        )
        return result.scalar_one_or_none()


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event_type: str, payload_json: str) -> SystemEvent:
        event = SystemEvent(event_type=event_type, payload_json=payload_json)
        self._session.add(event)
        await self._session.flush()
        return event

    async def list_recent(self, limit: int = 200) -> Sequence[SystemEvent]:
        result = await self._session.execute(select(SystemEvent).order_by(SystemEvent.id.desc()).limit(limit))
        return result.scalars().all()

    async def max_id(self) -> int:
        from sqlalchemy import func as sa_func

        result = await self._session.execute(select(sa_func.max(SystemEvent.id)))
        return int(result.scalar() or 0)


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, action: str, details_json: str, actor: str = "user") -> AuditLog:
        row = AuditLog(action=action, actor=actor, details_json=details_json)
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_recent(self, limit: int = 200) -> Sequence[AuditLog]:
        result = await self._session.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))
        return result.scalars().all()


class StrategyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_versions(self) -> Sequence[StrategyVersion]:
        result = await self._session.execute(select(StrategyVersion).order_by(StrategyVersion.id.desc()))
        return result.scalars().all()

    async def add_version(self, version: StrategyVersion) -> StrategyVersion:
        self._session.add(version)
        await self._session.flush()
        return version

    async def parameters_for(self, version_id: int) -> Sequence[StrategyParameter]:
        result = await self._session.execute(
            select(StrategyParameter).where(StrategyParameter.strategy_version_id == version_id)
        )
        return result.scalars().all()

    async def add_parameter(self, param: StrategyParameter) -> StrategyParameter:
        self._session.add(param)
        await self._session.flush()
        return param

    async def get_parameter(self, param_id: int) -> StrategyParameter | None:
        return await self._session.get(StrategyParameter, param_id)


class ReservationRepository:
    """Singleton CAS lock for opening intents. Not a Python bool."""

    SLOT_ID = 1

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_slot(self) -> OpenReservation:
        row = await self._session.get(OpenReservation, self.SLOT_ID)
        if row is None:
            row = OpenReservation(id=self.SLOT_ID, order_id=None)
            self._session.add(row)
            await self._session.flush()
        return row

    async def try_acquire(self, order_id: str, reason: str = "open") -> bool:
        await self.ensure_slot()
        result = await self._session.execute(
            update(OpenReservation)
            .where(OpenReservation.id == self.SLOT_ID, OpenReservation.order_id.is_(None))
            .values(order_id=order_id, held_reason=reason)
        )
        await self._session.flush()
        return result.rowcount == 1

    async def release(self, order_id: str | None = None) -> None:
        stmt = update(OpenReservation).where(OpenReservation.id == self.SLOT_ID)
        if order_id is not None:
            stmt = stmt.where(OpenReservation.order_id == order_id)
        await self._session.execute(stmt.values(order_id=None, held_reason=None))
        await self._session.flush()

    async def current_order_id(self) -> str | None:
        row = await self.ensure_slot()
        return row.order_id


class SnapshotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, equity: Decimal, available: Decimal, margin_used: Decimal) -> AccountSnapshot:
        row = AccountSnapshot(equity=equity, available=available, margin_used=margin_used)
        self._session.add(row)
        await self._session.flush()
        return row

    async def latest(self) -> AccountSnapshot | None:
        result = await self._session.execute(
            select(AccountSnapshot).order_by(AccountSnapshot.id.desc()).limit(1)
        )
        return result.scalar_one_or_none()


def effective_parameter_value(param: StrategyParameter) -> str:
    """enabled=false → strategy default; enabled=true → DB current_value."""
    return param.current_value if param.enabled else param.default_value
