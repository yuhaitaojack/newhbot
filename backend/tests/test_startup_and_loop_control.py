from __future__ import annotations

import time

from app.core.config import Settings
from app.core.enums import PositionSide
from app.execution.protocol import PositionView
from app.main import create_app
from starlette.testclient import TestClient
from tests.fakes import FakeExecutionClient


class FailingConnectExecution(FakeExecutionClient):
    async def connect(self) -> None:
        raise ConnectionError("fake connect failed")


class RecoveringWorkerExecution(FakeExecutionClient):
    async def worker_status(self) -> dict:
        return {"ready": False, "worker_state": "RECOVERING", "mode": "fake", "execution_enabled": False}


def _settings(db_file) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{db_file.as_posix()}",
        execution_worker_url="http://execution-test",
        execution_mode="mock",
        cors_origins="http://test",
        strategies_dir=str(db_file.parent / "strategy-versions"),
    )


def test_trading_start_and_stop_control_strategy_loop(tmp_path) -> None:
    fake = FakeExecutionClient()
    fake.candles = [{"timestamp": 1, "open": "100", "high": "101", "low": "99", "close": "100", "volume": "1"}]
    app = create_app(settings=_settings(tmp_path / "control.db"), execution=fake, bootstrap_schema=True)
    with TestClient(app) as client:
        started = client.post("/api/trading/start")
        assert started.json()["ok"] is True
        assert client.get("/api/strategy/loop").json()["running"] is True
        stopped = client.post("/api/trading/stop")
        assert stopped.json()["ok"] is True
        assert client.get("/api/strategy/loop").json()["running"] is False


def test_restart_resumes_only_after_safe_sync(tmp_path) -> None:
    db_file = tmp_path / "resume.db"
    settings = _settings(db_file)
    fake = FakeExecutionClient()
    app1 = create_app(settings=settings, execution=fake, bootstrap_schema=True)
    with TestClient(app1) as client:
        assert client.post("/api/trading/start").json()["ok"] is True

    app2 = create_app(settings=settings, execution=fake, bootstrap_schema=False)
    with TestClient(app2) as client:
        status = client.get("/api/status").json()
        assert status["system_state"] == "RUNNING"
        assert status["strategy_loop_running"] is True
        assert status["position"]["side"] == PositionSide.FLAT.value


def test_restart_does_not_resume_when_existing_exchange_mirror_is_stale(tmp_path) -> None:
    db_file = tmp_path / "stale.db"
    settings = _settings(db_file)
    fake = FakeExecutionClient()
    app1 = create_app(settings=settings, execution=fake, bootstrap_schema=True)
    with TestClient(app1) as client:
        assert client.post("/api/trading/start").json()["ok"] is True

    fake.get_position_error = True
    app2 = create_app(settings=settings, execution=fake, bootstrap_schema=False)
    with TestClient(app2) as client:
        status = client.get("/api/status").json()
        assert status["system_state"] == "RECOVERY"
        assert status["strategy_loop_running"] is False


def test_persisted_recovery_does_not_auto_resume_after_later_restart(tmp_path) -> None:
    db_file = tmp_path / "persisted-recovery.db"
    settings = _settings(db_file)
    fake = FakeExecutionClient()
    app1 = create_app(settings=settings, execution=fake, bootstrap_schema=True)
    with TestClient(app1) as client:
        assert client.post("/api/trading/start").json()["ok"] is True

    fake.get_position_error = True
    app2 = create_app(settings=settings, execution=fake, bootstrap_schema=False)
    with TestClient(app2) as client:
        assert client.get("/api/status").json()["system_state"] == "RECOVERY"

    fake.get_position_error = False
    app3 = create_app(settings=settings, execution=fake, bootstrap_schema=False)
    with TestClient(app3) as client:
        status = client.get("/api/status").json()
        assert status["system_state"] == "RECOVERY"
        assert status["strategy_loop_running"] is False


def test_start_enters_recovery_when_foreign_exchange_position_exists(tmp_path) -> None:
    fake = FakeExecutionClient()
    fake.positions["ETH-USD"] = PositionView(
        symbol="ETH-USD", side=PositionSide.LONG, size="1", entry_price="100"
    )
    app = create_app(settings=_settings(tmp_path / "foreign-position.db"), execution=fake, bootstrap_schema=True)
    with TestClient(app) as client:
        response = client.post("/api/trading/start")
        assert response.json() == {
            "ok": False,
            "reason": "foreign exchange position present; recovery required",
        }
        status = client.get("/api/status").json()
        assert status["system_state"] == "RECOVERY"
        assert status["strategy_loop_running"] is False
        assert status["position"]["side"] == PositionSide.FLAT.value
        assert fake.place_calls == 0


def test_start_enters_recovery_when_worker_startup_raises(tmp_path) -> None:
    fake = FailingConnectExecution()
    app = create_app(settings=_settings(tmp_path / "worker-start-failure.db"), execution=fake, bootstrap_schema=True)
    with TestClient(app) as client:
        response = client.post("/api/trading/start")
        assert response.status_code == 200
        assert response.json() == {
            "ok": False,
            "reason": "execution worker startup failed; recovery required",
        }
        status = client.get("/api/status").json()
        assert status["system_state"] == "RECOVERY"
        assert status["trading_enabled"] is False
        assert status["strategy_loop_running"] is False
        assert fake.place_calls == 0


def test_start_enters_recovery_when_worker_health_query_raises(tmp_path) -> None:
    fake = FakeExecutionClient()
    fake.health_error = True
    app = create_app(settings=_settings(tmp_path / "worker-health-failure.db"), execution=fake, bootstrap_schema=True)
    with TestClient(app) as client:
        response = client.post("/api/trading/start")
        assert response.status_code == 200
        assert response.json() == {
            "ok": False,
            "reason": "execution worker health query failed; recovery required",
        }
        status = client.get("/api/status").json()
        assert status["system_state"] == "RECOVERY"
        assert status["strategy_loop_running"] is False
        assert fake.place_calls == 0


def test_start_enters_recovery_when_worker_is_unreachable(tmp_path) -> None:
    fake = FakeExecutionClient()
    fake.healthy = False
    app = create_app(settings=_settings(tmp_path / "worker-unreachable.db"), execution=fake, bootstrap_schema=True)
    with TestClient(app) as client:
        response = client.post("/api/trading/start")
        assert response.status_code == 200
        assert response.json() == {
            "ok": False,
            "reason": "execution worker unreachable; recovery required",
        }
        status = client.get("/api/status").json()
        assert status["system_state"] == "RECOVERY"
        assert status["strategy_loop_running"] is False
        assert fake.place_calls == 0


def test_strategy_loop_enters_recovery_and_stops_when_worker_recovers_badly(tmp_path) -> None:
    fake = RecoveringWorkerExecution()
    app = create_app(settings=_settings(tmp_path / "loop-worker-recovery.db"), execution=fake, bootstrap_schema=True)
    with TestClient(app) as client:
        loop = app.state.container.strategy_loop
        loop._poll_seconds = 0.01
        assert client.post("/api/trading/start").json()["ok"] is True
        time.sleep(0.15)
        status = client.get("/api/status").json()
        assert status["system_state"] == "RECOVERY"
        assert status["strategy_loop_running"] is False
        assert status["strategy_loop_last_error"] == "worker_not_ready:RECOVERING"
        assert fake.place_calls == 0


def test_strategy_loop_enters_recovery_when_worker_status_query_fails(tmp_path) -> None:
    fake = FakeExecutionClient()
    app = create_app(settings=_settings(tmp_path / "loop-worker-status-error.db"), execution=fake, bootstrap_schema=True)
    with TestClient(app) as client:
        loop = app.state.container.strategy_loop
        loop._poll_seconds = 0.01
        assert client.post("/api/trading/start").json()["ok"] is True
        fake.worker_status_error = True
        time.sleep(0.08)
        status = client.get("/api/status").json()
        assert status["system_state"] == "RECOVERY"
        assert status["strategy_loop_running"] is False
        assert status["strategy_loop_last_error"] == "worker_status_query_failed:TimeoutError"
        assert fake.place_calls == 0


def test_strategy_loop_enters_recovery_when_candle_query_fails(tmp_path) -> None:
    fake = FakeExecutionClient()
    fake.candles = [{"timestamp": 1, "open": "100", "high": "101", "low": "99", "close": "100", "volume": "1"}]
    app = create_app(settings=_settings(tmp_path / "loop-candle-error.db"), execution=fake, bootstrap_schema=True)
    with TestClient(app) as client:
        loop = app.state.container.strategy_loop
        loop._poll_seconds = 0.01
        assert client.post("/api/trading/start").json()["ok"] is True
        fake.get_candles_error = True
        time.sleep(0.08)
        status = client.get("/api/status").json()
        assert status["system_state"] == "RECOVERY"
        assert status["strategy_loop_running"] is False
        assert status["strategy_loop_last_error"] == "candle_query_failed:TimeoutError"
        assert fake.place_calls == 0


def test_strategy_loop_enters_recovery_when_position_query_fails(tmp_path) -> None:
    fake = FakeExecutionClient()
    fake.candles = [{"timestamp": 1, "open": "100", "high": "101", "low": "99", "close": "100", "volume": "1"}]
    app = create_app(settings=_settings(tmp_path / "loop-position-error.db"), execution=fake, bootstrap_schema=True)
    with TestClient(app) as client:
        loop = app.state.container.strategy_loop
        loop._poll_seconds = 0.01
        assert client.post("/api/trading/start").json()["ok"] is True
        time.sleep(0.03)
        fake.candles = [{"timestamp": 2, "open": "100", "high": "101", "low": "99", "close": "100", "volume": "1"}]
        fake.get_position_error = True
        time.sleep(0.08)
        status = client.get("/api/status").json()
        assert status["system_state"] == "RECOVERY"
        assert status["strategy_loop_running"] is False
        assert status["strategy_loop_last_error"] == "position_query_failed:TimeoutError"
        assert fake.place_calls == 0


def test_strategy_loop_enters_recovery_when_position_is_unknown(tmp_path) -> None:
    fake = FakeExecutionClient()
    fake.candles = [{"timestamp": 1, "open": "100", "high": "101", "low": "99", "close": "100", "volume": "1"}]
    app = create_app(settings=_settings(tmp_path / "loop-position-unknown.db"), execution=fake, bootstrap_schema=True)
    with TestClient(app) as client:
        loop = app.state.container.strategy_loop
        loop._poll_seconds = 0.01
        assert client.post("/api/trading/start").json()["ok"] is True
        time.sleep(0.03)
        fake.candles = [{"timestamp": 2, "open": "100", "high": "101", "low": "99", "close": "100", "volume": "1"}]
        fake.positions["BTC-USD"] = PositionView(symbol="BTC-USD", side=PositionSide.UNKNOWN, size="0")
        time.sleep(0.08)
        status = client.get("/api/status").json()
        assert status["system_state"] == "RECOVERY"
        assert status["strategy_loop_running"] is False
        assert status["strategy_loop_last_error"] == "position_unknown"
        assert fake.place_calls == 0


def test_strategy_loop_runtime_failure_enters_recovery(tmp_path) -> None:
    fake = FakeExecutionClient()
    fake.candles = [{"timestamp": 1, "open": "100", "high": "101", "low": "99", "close": "100", "volume": "1"}]
    app = create_app(settings=_settings(tmp_path / "loop-runtime-error.db"), execution=fake, bootstrap_schema=True)

    async def fail(*args, **kwargs):
        raise RuntimeError("runtime failed")

    app.state.container.strategy_runtime.evaluate = fail
    app.state.container.strategy_loop._runtime = app.state.container.strategy_runtime
    with TestClient(app) as client:
        loop = app.state.container.strategy_loop
        loop._poll_seconds = 0.01
        assert client.post("/api/trading/start").json()["ok"] is True
        time.sleep(0.03)
        fake.candles = [{"timestamp": 2, "open": "100", "high": "101", "low": "99", "close": "100", "volume": "1"}]
        time.sleep(0.08)
        status = client.get("/api/status").json()
        assert status["system_state"] == "RECOVERY"
        assert status["strategy_loop_running"] is False
        assert status["strategy_loop_last_error"] == "strategy_evaluation_failed:RuntimeError"
        assert fake.place_calls == 0


def test_strategy_loop_unexpected_failure_enters_recovery_and_stops(tmp_path) -> None:
    fake = FakeExecutionClient()
    app = create_app(settings=_settings(tmp_path / "loop-unexpected-error.db"), execution=fake, bootstrap_schema=True)

    async def fail(*args, **kwargs):
        raise RuntimeError("unexpected loop failure")

    app.state.container.strategy_loop._tick = fail
    with TestClient(app) as client:
        loop = app.state.container.strategy_loop
        loop._poll_seconds = 0.01
        assert client.post("/api/trading/start").json()["ok"] is True
        time.sleep(0.08)
        status = client.get("/api/status").json()
        assert status["system_state"] == "RECOVERY"
        assert status["strategy_loop_running"] is False
        assert status["strategy_loop_last_error"] == "strategy_loop_failed:RuntimeError"
        assert fake.place_calls == 0
