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
