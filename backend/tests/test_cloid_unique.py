from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.enums import OrderStatus
from app.core.ids import new_cloid, new_id
from app.db import create_all_for_tests, create_engine, create_session_factory
from app.models import Order
from app.core.config import Settings


@pytest.mark.asyncio
async def test_duplicate_cloid_rejected_by_sqlite(tmp_path) -> None:
    settings = Settings(database_url=f"sqlite+aiosqlite:///{(tmp_path / 'uq.db').as_posix()}")
    engine = create_engine(settings)
    await create_all_for_tests(engine)
    factory = create_session_factory(engine)
    cloid = new_cloid()
    async with factory() as session:
        session.add(
            Order(
                id=new_id(),
                intent_id=new_id(),
                request_id=new_id(),
                cloid=cloid,
                symbol="BTC-USD",
                side="BUY",
                order_type="MARKET",
                quantity=Decimal("1"),
                reduce_only=False,
                status=OrderStatus.PENDING_SUBMISSION.value,
            )
        )
        await session.commit()
        session.add(
            Order(
                id=new_id(),
                intent_id=new_id(),
                request_id=new_id(),
                cloid=cloid,
                symbol="BTC-USD",
                side="BUY",
                order_type="MARKET",
                quantity=Decimal("1"),
                reduce_only=False,
                status=OrderStatus.PENDING_SUBMISSION.value,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_intent_id_rejected_by_sqlite(tmp_path) -> None:
    settings = Settings(database_url=f"sqlite+aiosqlite:///{(tmp_path / 'intent.db').as_posix()}")
    engine = create_engine(settings)
    await create_all_for_tests(engine)
    factory = create_session_factory(engine)
    intent_id = new_id()
    async with factory() as session:
        session.add(
            Order(
                id=new_id(),
                intent_id=intent_id,
                request_id=new_id(),
                cloid=new_cloid(),
                symbol="BTC-USD",
                side="BUY",
                order_type="MARKET",
                quantity=Decimal("1"),
                reduce_only=False,
                status=OrderStatus.FILLED.value,
            )
        )
        await session.commit()
        session.add(
            Order(
                id=new_id(),
                intent_id=intent_id,
                request_id=new_id(),
                cloid=new_cloid(),
                symbol="ETH-USD",
                side="BUY",
                order_type="MARKET",
                quantity=Decimal("1"),
                reduce_only=False,
                status=OrderStatus.FILLED.value,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
    await engine.dispose()
