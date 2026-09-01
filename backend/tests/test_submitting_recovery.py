from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.config import Settings
from app.core.enums import OrderSide, OrderStatus, OrderType, PositionSide, SignalType, SystemState
from app.core.ids import new_cloid, new_id
from app.execution.protocol import FillView, OrderView, PositionView
from app.main import create_app
from app.models import Order
from app.repositories import OrderRepository, ReservationRepository, SettingsRepository
from tests.fakes import FakeExecutionClient


def _settings(db_file) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{db_file.as_posix()}",
        execution_worker_url="http://execution-test",
        execution_mode="mock",
        cors_origins="http://test",
    )


async def _plant_submitting(container, *, cloid: str, order_id: str) -> None:
    async with container.session_factory() as session:
        settings = await SettingsRepository(session).get()
        settings.trading_enabled = True
        acquired = await ReservationRepository(session).try_acquire(order_id, reason="open")
        assert acquired is True
        session.add(
            Order(
                id=order_id,
                intent_id=new_id(),
                request_id=new_id(),
                cloid=cloid,
                symbol=settings.trading_pair,
                side=OrderSide.BUY.value,
                order_type=OrderType.MARKET.value,
                quantity=Decimal("1"),
                reduce_only=False,
                status=OrderStatus.SUBMITTING.value,
            )
        )
        await session.commit()


def _seed_filled_on_exchange(fake: FakeExecutionClient, *, cloid: str, symbol: str = "BTC-USD") -> None:
    fake.orders[cloid] = OrderView(
        cloid=cloid,
        exchange_oid="99",
        symbol=symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        filled_quantity=Decimal("1"),
        reduce_only=False,
        status=OrderStatus.FILLED,
        price=Decimal("100"),
    )
    fake.fills.append(
        FillView(cloid=cloid, symbol=symbol, side=OrderSide.BUY, price=Decimal("100"), quantity=Decimal("1"))
    )
    fake.positions[symbol] = PositionView(
        symbol=symbol, side=PositionSide.LONG, size=Decimal("1"), entry_price=Decimal("100")
    )


@pytest.mark.asyncio
async def test_submitting_crash_recovers_existing_order_without_resubmit(tmp_path) -> None:
    """A: SUBMITTING crash, order already on exchange, restore FILLED, never place_order again."""
    db_file = tmp_path / "crash_a.db"
    fake = FakeExecutionClient()
    settings = _settings(db_file)
    cloid = new_cloid()
    order_id = new_id()
    app1 = create_app(settings=settings, execution=fake, bootstrap_schema=True)
    async with app1.router.lifespan_context(app1):
        await _plant_submitting(app1.state.container, cloid=cloid, order_id=order_id)
        _seed_filled_on_exchange(fake, cloid=cloid)
    assert fake.place_calls == 0

    app2 = create_app(settings=settings, execution=fake, bootstrap_schema=False)
    async with app2.router.lifespan_context(app2):
        async with app2.state.container.session_factory() as session:
            row = await OrderRepository(session).get_by_cloid(cloid)
            assert row is not None
            assert row.status == OrderStatus.FILLED.value
            assert "will not resubmit" in (row.error_message or "")
            assert await ReservationRepository(session).current_order_id() == order_id
            blocked = await app2.state.container.controller.handle_signal(session, SignalType.LONG)
            assert blocked["accepted"] is False
        assert fake.place_calls == 0


@pytest.mark.asyncio
async def test_submitting_crash_absent_order_safe_end_releases_reservation(tmp_path) -> None:
    """B: SUBMITTING crash, no order/fill, FLAT position → REJECTED, reservation released, new LONG allowed."""
    db_file = tmp_path / "crash_b.db"
    fake = FakeExecutionClient()
    settings = _settings(db_file)
    cloid = new_cloid()
    order_id = new_id()
    app1 = create_app(settings=settings, execution=fake, bootstrap_schema=True)
    async with app1.router.lifespan_context(app1):
        await _plant_submitting(app1.state.container, cloid=cloid, order_id=order_id)
    assert fake.place_calls == 0

    app2 = create_app(settings=settings, execution=fake, bootstrap_schema=False)
    async with app2.router.lifespan_context(app2):
        async with app2.state.container.session_factory() as session:
            row = await OrderRepository(session).get_by_cloid(cloid)
            assert row is not None
            assert row.status == OrderStatus.REJECTED.value
            assert await ReservationRepository(session).current_order_id() is None
            settings_row = await SettingsRepository(session).get()
            if settings_row.system_state != SystemState.RUNNING.value:
                started = await app2.state.container.controller.start(session)
                assert started["ok"] is True
            opened = await app2.state.container.controller.handle_signal(session, SignalType.LONG)
            assert opened["accepted"] is True
        assert fake.place_calls == 1


@pytest.mark.asyncio
async def test_submitting_crash_unconfirmed_stays_unknown_blocks_open(tmp_path) -> None:
    """C+D: query failure keeps UNKNOWN/RECOVERY, reservation held, LONG/SHORT rejected, no place_order."""
    db_file = tmp_path / "crash_c.db"
    fake = FakeExecutionClient()
    fake.get_order_error = True
    settings = _settings(db_file)
    cloid = new_cloid()
    order_id = new_id()
    app1 = create_app(settings=settings, execution=fake, bootstrap_schema=True)
    async with app1.router.lifespan_context(app1):
        await _plant_submitting(app1.state.container, cloid=cloid, order_id=order_id)
    assert fake.place_calls == 0

    app2 = create_app(settings=settings, execution=fake, bootstrap_schema=False)
    async with app2.router.lifespan_context(app2):
        async with app2.state.container.session_factory() as session:
            row = await OrderRepository(session).get_by_cloid(cloid)
            assert row is not None
            assert row.status == OrderStatus.UNKNOWN.value
            assert await ReservationRepository(session).current_order_id() == order_id
            settings_row = await SettingsRepository(session).get()
            assert settings_row.system_state == SystemState.RECOVERY.value
            blocked_short = await app2.state.container.controller.handle_signal(session, SignalType.SHORT)
            assert blocked_short["accepted"] is False
            blocked_long = await app2.state.container.controller.handle_signal(session, SignalType.LONG)
            assert blocked_long["accepted"] is False
        assert fake.place_calls == 0
