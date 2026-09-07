from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.fakes import FakeExecutionClient


@pytest.fixture
def fake_execution() -> FakeExecutionClient:
    return FakeExecutionClient()


@pytest.fixture
def app_client(fake_execution: FakeExecutionClient, tmp_path):
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        execution_worker_url="http://execution-test",
        execution_mode="mock",
        cors_origins="http://test",
        strategies_dir=str(tmp_path / "strategy-versions"),
    )
    app = create_app(settings=settings, execution=fake_execution, bootstrap_schema=True)
    with TestClient(app) as client:
        yield client, app, fake_execution
