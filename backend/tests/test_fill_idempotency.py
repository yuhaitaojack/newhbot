from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.enums import OrderStatus
from app.core.ids import new_cloid, new_id
from app.core.config import Settings
from app.db import create_all_for_tests, create_engine, create_session_factory
from app.models import Fill, Order
from app.repositories import FillRepository


@pytest.mark.asyncio
async def test_duplicate_exchange_fill_id_is_idempotent(tmp_path) -> None:
    settings = Settings(database_url=f"sqlite+aiosqlite:///{(tmp_path / 'fills.db').as_posix()}")
    engine = create_engine(settings)
    await create_all_for_tests(engine)
    factory = create_session_factory(engine)
    cloid = new_cloid()
    order_id = new_id()
    async with factory() as session:
        session.add(
            Order(
                id=order_id,
                intent_id=new_id(),
                request_id=new_id(),
                cloid=cloid,
                symbol="BTC-USD",
                side="BUY",
                order_type="MARKET",
                quantity=Decimal("1"),
                reduce_only=False,
                status=OrderStatus.FILLED.value,
            )
        )
        await session.commit()
        first, created_first = await FillRepository(session).add(
            Fill(
                id=new_id(),
                order_id=order_id,
                cloid=cloid,
                symbol="BTC-USD",
                side="BUY",
                price=Decimal("100"),
                quantity=Decimal("1"),
                exchange_fill_id="77",
            )
        )
        second, created_second = await FillRepository(session).add(
            Fill(
                id=new_id(),
                order_id=order_id,
                cloid=cloid,
                symbol="BTC-USD",
                side="BUY",
                price=Decimal("100"),
                quantity=Decimal("1"),
                exchange_fill_id="77",
            )
        )
        await session.commit()
        assert created_first is True
        assert created_second is False
        assert first.id == second.id
        rows = await FillRepository(session).list_recent()
        assert len(rows) == 1
