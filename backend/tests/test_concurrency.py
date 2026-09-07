from __future__ import annotations

import asyncio

import pytest

from app.core.config import Settings
from app.core.enums import SignalType
from app.main import create_app
from tests.fakes import FakeExecutionClient


@pytest.mark.asyncio
async def test_concurrent_long_signals_only_one_place_order(tmp_path) -> None:
    db_file = tmp_path / "concurrent.db"
    fake = FakeExecutionClient()
    fake.place_delay = 0.2
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{db_file.as_posix()}",
        execution_worker_url="http://execution-test",
        execution_mode="mock",
        cors_origins="http://test",
    )
    app = create_app(settings=settings, execution=fake, bootstrap_schema=True)
    async with app.router.lifespan_context(app):
        container = app.state.container
        async with container.session_factory() as session:
            started = await container.controller.start(session)
            assert started["ok"] is True

        async def fire() -> dict:
            async with container.session_factory() as session:
                return await container.controller.handle_signal(session, SignalType.LONG)

        first, second = await asyncio.gather(fire(), fire())
        accepted = sorted([first["accepted"], second["accepted"]])
        assert accepted == [False, True]
        assert fake.place_calls == 1


@pytest.mark.asyncio
async def test_signal_is_rejected_while_manual_close_is_in_progress(tmp_path) -> None:
    db_file = tmp_path / "close_concurrent.db"
    fake = FakeExecutionClient()
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{db_file.as_posix()}",
        execution_worker_url="http://execution-test",
        execution_mode="mock",
        cors_origins="http://test",
    )
    app = create_app(settings=settings, execution=fake, bootstrap_schema=True)
    async with app.router.lifespan_context(app):
        container = app.state.container
        async with container.session_factory() as session:
            started = await container.controller.start(session)
            assert started["ok"] is True
            opened = await container.controller.handle_signal(session, SignalType.LONG)
            assert opened["accepted"] is True

        fake.place_delay = 0.2

        async def close() -> dict:
            async with container.session_factory() as session:
                return await container.controller.close_and_continue(session)

        async def signal_during_close() -> dict:
            await asyncio.sleep(0.03)
            async with container.session_factory() as session:
                return await container.controller.handle_signal(session, SignalType.SHORT)

        close_result, signal_result = await asyncio.gather(close(), signal_during_close())

        assert close_result["ok"] is True
        assert signal_result["accepted"] is False
        assert signal_result["reason"] == "close in progress"
        assert fake.place_calls == 2
        async with container.session_factory() as session:
            final = await container.execution.get_position("BTC-USD")
            assert final.side.value == "FLAT"
