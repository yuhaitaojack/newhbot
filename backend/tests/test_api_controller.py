from __future__ import annotations

from app.core.enums import OrderStatus, PositionSide


def test_settings_persist_roundtrip(app_client) -> None:
    client, _, _ = app_client
    original = client.get("/api/settings")
    assert original.status_code == 200
    updated = client.put("/api/settings", json={"leverage": 3, "trading_pair": "ETH-USD"})
    assert updated.status_code == 200
    body = updated.json()
    assert body["leverage"] == 3
    assert body["trading_pair"] == "ETH-USD"
    again = client.get("/api/settings")
    assert again.json()["leverage"] == 3
    assert again.json()["trading_pair"] == "ETH-USD"


def test_strategy_parameter_effective_value_in_api(app_client) -> None:
    client, _, _ = app_client
    response = client.get("/api/strategy")
    assert response.status_code == 200
    params = response.json()["parameters"]
    assert params
    lookback = next(item for item in params if item["name"] == "lookback")
    assert lookback["enabled"] is False
    assert lookback["effective_value"] == lookback["default_value"]


def test_health_and_status(app_client) -> None:
    client, _, _ = app_client
    health = client.get("/api/health")
    assert health.status_code == 200
    status = client.get("/api/status")
    assert status.status_code == 200
    assert "system_state" in status.json()


def test_flat_long_opens_then_long_long_rejected(app_client) -> None:
    client, _, _ = app_client
    start = client.post("/api/trading/start")
    assert start.status_code == 200
    assert start.json()["ok"] is True

    first = client.post("/api/trading/signal", json={"signal": "LONG"})
    assert first.status_code == 200
    assert first.json()["accepted"] is True
    pos = client.get("/api/positions")
    assert pos.json()[0]["side"] == PositionSide.LONG.value

    second = client.post("/api/trading/signal", json={"signal": "LONG"})
    assert second.json()["accepted"] is False

    reverse = client.post("/api/trading/signal", json={"signal": "SHORT"})
    assert reverse.json()["accepted"] is False
    assert "reverse" in reverse.json()["reason"]


def test_short_then_long_rejected(app_client) -> None:
    client, _, _ = app_client
    client.post("/api/trading/start")
    opened = client.post("/api/trading/signal", json={"signal": "SHORT"})
    assert opened.json()["accepted"] is True
    blocked = client.post("/api/trading/signal", json={"signal": "LONG"})
    assert blocked.json()["accepted"] is False


def test_unknown_blocks_new_open(app_client) -> None:
    client, _, fake = app_client
    client.post("/api/trading/start")
    fake.place_mode = "network_before_accept"
    unknown = client.post("/api/trading/signal", json={"signal": "LONG"})
    assert unknown.json()["status"] == OrderStatus.UNKNOWN.value
    orders = client.get("/api/orders")
    assert orders.json()[0]["status"] == OrderStatus.UNKNOWN.value
    fake.place_mode = "fill"
    blocked = client.post("/api/trading/signal", json={"signal": "LONG"})
    assert blocked.json()["accepted"] is False
    assert fake.place_calls == 1


def test_timeout_after_accept_does_not_resubmit(app_client) -> None:
    client, _, fake = app_client
    client.post("/api/trading/start")
    fake.place_mode = "timeout_after_accept"
    result = client.post("/api/trading/signal", json={"signal": "LONG"})
    body = result.json()
    assert "cloid" in body
    orders = client.get("/api/orders")
    assert len(orders.json()) == 1


def test_recovery_blocks_open(app_client) -> None:
    client, _, fake = app_client
    client.post("/api/trading/start")
    fake.place_mode = "network_before_accept"
    client.post("/api/trading/signal", json={"signal": "LONG"})
    status = client.get("/api/status")
    assert status.json()["system_state"] == "RECOVERY"
    fake.place_mode = "fill"
    blocked = client.post("/api/trading/signal", json={"signal": "SHORT"})
    assert blocked.json()["accepted"] is False


def test_short_then_short_rejected(app_client) -> None:
    client, _, _ = app_client
    client.post("/api/trading/start")
    opened = client.post("/api/trading/signal", json={"signal": "SHORT"})
    assert opened.json()["accepted"] is True
    blocked = client.post("/api/trading/signal", json={"signal": "SHORT"})
    assert blocked.json()["accepted"] is False


def test_settings_survive_app_restart(tmp_path) -> None:
    from starlette.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app
    from tests.fakes import FakeExecutionClient

    db_file = tmp_path / "settings.db"
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{db_file.as_posix()}",
        execution_worker_url="http://execution-test",
        execution_mode="mock",
        cors_origins="http://test",
    )
    fake = FakeExecutionClient()
    app1 = create_app(settings=settings, execution=fake)
    with TestClient(app1) as client:
        updated = client.put("/api/settings", json={"leverage": 7, "trading_pair": "ETH-USD"})
        assert updated.status_code == 200
        assert updated.json()["leverage"] == 7
    app2 = create_app(settings=settings, execution=fake)
    with TestClient(app2) as client:
        again = client.get("/api/settings")
        assert again.status_code == 200
        assert again.json()["leverage"] == 7
        assert again.json()["trading_pair"] == "ETH-USD"


def test_control_buttons(app_client) -> None:
    client, _, _ = app_client
    assert client.post("/api/trading/start").json()["ok"] is True
    assert client.post("/api/trading/stop").json()["ok"] is True
    client.post("/api/trading/start")
    client.post("/api/trading/signal", json={"signal": "LONG"})
    closed = client.post("/api/trading/close-and-continue")
    assert closed.status_code == 200
    estop = client.post("/api/trading/emergency-stop")
    assert estop.status_code == 200
    status = client.get("/api/status")
    assert status.json()["estop"] is True


def test_lists_and_websocket_hello(app_client) -> None:
    client, _, _ = app_client
    assert client.get("/api/orders").status_code == 200
    assert client.get("/api/fills").status_code == 200
    assert client.get("/api/trades").status_code == 200
    assert client.get("/api/events").status_code == 200
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
